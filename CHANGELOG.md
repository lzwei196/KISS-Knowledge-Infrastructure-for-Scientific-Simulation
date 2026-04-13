# Knowledge Dissection Toolkit — Changelog

## v5.0.1 (2026-04-13) — "SUMMA Deep Dive"

Post-release patch: 8 bugs fixed in SUMMA KI through systematic source-code analysis + Bengbu revalidation. Final result: **NSE=0.393, r=0.652, PBIAS=-15%** (uncalibrated, Bengbu 1981-1985). New cross-model patterns for land cover classification mismatch and mixed output units.

### Fixed: SUMMA KI (7 bugs, 6 new triplets, 1 new tool)

**Bug fixes from Fortran source code analysis:**
- `set_trial_parameters.py` — `vGn_alpha` range (0.001,10) → (-1.0,-0.01). SUMMA uses negative matric head convention. Positive values cause NaN in Richards solver (dt_019)
- `configure_decisions.py` — 3 fatal default incompatibilities:
  - `fDerivMeth=numericl` → `analytic` (numericl completely broken, soilLiqFlx.f90:305) (dt_020)
  - `groundwatr=qTopmodl` + `bcLowrSoiH=drainage` → `noXplict` + `drainage` (mDecisions.f90:660) (dt_021)
  - `vegeParTbl=MODIFIED_IGBP_MODIS_NOAH` needs MPTABLE section → default `USGS` (dt_022)
- `configure_decisions.py` — Added 8 hard incompatibility checks from mDecisions.f90 (errors, not warnings)

**Forcing conversion fixes:**
- `convert_vic_forcing_to_summa.py` — VIC column order: HydroCraft uses AIR_TEMP,PREC,PRES,SW,LW,VP,WIND (7 cols), not classic PREC,TMAX,TMIN,WIND,SW,LW,PRES,QAIR (8 cols). Added `--column_order hydrocraft|classic` flag (dt_023)
- `convert_vic_forcing_to_summa.py` — VP (kPa) → specific humidity (kg/kg) conversion. VIC col 5 is vapor pressure, not specific humidity. Without conversion, humidity is 100x too high → NaN in energy balance

**Land cover classification mismatch (dt_024):**
- `create_gru_hru.py` — AVHRR uses IGBP-DIS classification, SUMMA VEGPARM.TBL uses USGS 27-class. Class 11 = IGBP "Wetland/Cropland" but USGS "Deciduous Broadleaf Forest" (20m canopy). 74% of Bengbu basin was treated as tall forest instead of rice paddies → `canopySnow` convergence failure. Added IGBP→USGS crosswalk table.
- Added `vegeParTbl` decision guidance: USGS for NA basins, MODIFIED_IGBP_MODIS_NOAH for global (with agent prompt to ask user)

**Domain setup improvements:**
- `create_gru_hru.py` — Default to 1 HRU per GRU (`--multi_hru` flag for sub-grid heterogeneity). 8304 HRUs → 224 HRUs cut runtime from 35h to 12 min.
- Documented HRU scaling guidance from Clark et al. 2015

**New tool:**
- `run_summa_twophase.py` — Two-phase execution (presTemp spinup → nrg_flux production) with automatic fallback. Addresses cold-start convergence failure on subtropical basins.

**Regional applicability documented:**
- SUMMA `nrg_flux` + `canopySnow` cannot converge on cold-start for distributed subtropical basins (confirmed on Bengbu, all 224 GRUs fail at first freezing event)
- `presTemp` runs but produces zero ET → zero runoff (diagnostic mode only)
- Recommended: cold-region/mountain basins. For subtropical: use VIC, mHM, HYPE, wflow
- Bengbu result with presTemp: r=0.893 (excellent timing), PBIAS=-99.7% (no volume — presTemp limitation)

**Triplets:** 18 → 24 (+6: dt_019 through dt_024)
**SKILL.md:** 161 → 308 lines

## v5.0.0 (2026-04-11) — "Docs First, Fix Right"

Major release focused on **debugging methodology** and **KI tool validation** across 6 models. Driven by the principle: **when something breaks, read the docs and working examples first — never write debug scripts**.

### New: Debugging Protocol (Rule 0)
- Added to **all 124 SKILL.md** files, PREFLIGHT.md ("Three Rules"), cli_agent.py, SKILL_TEMPLATE.md
- 4-step protocol: (1) check triplets → (2) read official docs → (3) find working examples → (4) fix the tool
- Motivated by mizuRoute/wflow revalidation where 20+ debug scripts were written when answers were in the docs

### New: Preflight Checks for All Models
- Generated `preflight_check.py` for **94 auto-dissected models** (29 showcase already had them)
- All 124 SKILL.md files now reference `preflight_check.py`
- Extracted binary/package checks from SKILL.md where available

### Fixed: mizuRoute KI (3 tool bugs)
- `create_remap_weights.py` — Added `num_qhru`, 2-dimension format, correct i/j grid indices (from Input_files.rst)
- `generate_control_file.py` — Added `<param_nml>`, fixed `route_opt` (0=accumRunoff not IRF), added 7 remap variable keys, `<IRFroutedRunoff>` toggle
- Validated: Bengbu r=0.84 vs previous run, Xixian working

### Fixed: wflow KI (3 interacting LDD bugs + 1 staticmaps bug)
- `run_hydromt_build.py` — WhiteboxTools breach+D8 replacing naive D8; full DEM (no masking); dual-space boundary check (numpy + wflow transpose+y-reverse)
- dt_w014, dt_w027 rewritten with root causes; dt_w031 new (Brooks-Corey layer dimension)
- SKILL.md "Critical: LDD Generation" section documenting all 3 problems
- Validated: Bengbu (1081 m³/s, 18s), Xixian working

### Fixed: CRHM KI (7 tool bugs + new derive_parameters tool)
- `convert_forcing.py` — Single description line in .obs (dt_020)
- `create_prj_file.py` — Flat module format (dt_019), no blank lines, Display_Variable with module prefix, `--derived_params` integration
- `select_modules.py` — Full 15-module mountain chain from Belly River, auto basin type detection from HRU config
- **NEW** `derive_parameters.py` — Derives ALL module params from HWSD + DEM + Fang et al. (2013): soil (porosity×depth), obs (lapse, precip_elev_adj), evap, walmsley_wind, pbsm, crack, routing
- Validated: Ghost River, Threepoint Creek, Cherry Creek (autonomous end-to-end)

### Fixed: SFINCS KI (7 tool bugs)
- `build_sfincs_topobathy.py` — mask=1 for active cells, not mask=3 (dt_v009)
- `prepare_sfincs_rainfall.py` — CMFD kg/m²/s→mm/hr ×3600 (dt_v010), date filter (dt_v011), bbox clip with dask, ASCII output not NetCDF (dt_v012)
- `cama_to_sfincs_boundary.py` — Time filter to requested period (dt_v013)
- `generate_sfincs_inp.py` — File existence check in output_dir (dt_v014)
- Validated: Bengbu 4 events (2003, 1982, 1983, 1984), CaMa discharge + CMFD rainfall coupling

### Updated: MODFLOW6 KI
- SKILL.md item 10: Layer 1 K from HWSD (not GLHYMPS bedrock) — validated Wangjiaba r=0.56 vs r=0.41
- Validated: Wangjiaba r=0.556 vs GRACE, Xixian r=0.395 vs GRACE (new runs)

### Revalidation Database
- **16/28 models** now have runs (up from 10)
- Added: OGGM (3 regions), SFINCS (3 sites), MODFLOW6 (3 sites), DLBreach (3 cases), SWMM (2 sites), Pywr (1 site)
- 89 total runs across all models

### New Diagnostic Triplets
- CRHM: dt_019 (Macro format crash), dt_020 (.obs header)
- wflow: dt_w027 rewritten (3 LDD causes), dt_w014 rewritten (dual-space boundary), dt_w031 (layer dim)
- SFINCS: dt_v009 through dt_v014 (6 new triplets)
- Total: **~20 new/rewritten triplets** across 4 models

---

## v4.0.0 (2026-03-30) — "Real Binary, Real Grid, Real Data"

Major release focused on running actual model binaries in distributed/gridded mode with correct data handling. Driven by the principle: **models must run the original way, the most complicated way**.

### New: Shared Utility Library (`ki_tools_common/`)
- **8 modules** consolidating code duplicated across 435+ model tools:
  - `units.py` — 40+ named conversion constants, 30+ functions, universal `convert()` dispatcher
  - `humidity.py` — Single canonical Tetens implementation (replaces 17 independent versions)
  - `netcdf_utils.py` — Coordinate discovery, basin masking, CMFD/MSWX loaders
  - `validation.py` — Physical range checks with unit-trap heuristics
  - `metrics.py` — NSE, KGE, PBIAS, RMSE, r (all NaN-safe)
  - `io_helpers.py` — Standard JSON output, Bengbu/FLUXNET readers
  - `forcing_sources.py` — CMFD/MSWX/ERA5/FLUXNET variable mappings with conversion factors
- 45 unit tests (`tests/test_units.py`)
- `pip install -e .` ready via `pyproject.toml`

### New: Validation Enforcement (`validators/`)
- **`preflight_forcing.py`** (1,144 lines) — Checks forcing data against physical ranges before model run. Auto-detects CMFD/MSWX/ERA5/FLUXNET. Catches the #1 silent error: unit mismatches.
- **`check_calval_split.py`** (559 lines) — Detects data leakage (calibrating and validating on same period). Found 5 models with inflated metrics.
- **`standard_calval.py`** (313 lines) — Standard cal/val helper: spinup=1980, cal=1981-1985, val=1986-1990. Provides `calval_objective()` wrapper for scipy.optimize that enforces temporal split.

### New: 5 Model Binaries Rebuilt from Source
- **ESMF 9.0.0-beta** built from source (gfortran + OpenMPI) — unblocked 3 climate models
- **CLM5/CTSM** `cesm.exe` (19 MB) — CIME build with ESMF, NetCDF multiarch fix
- **FATES** `cesm.exe` (18 MB) — FATES-enabled compset (I2000Clm60FatesRs)
- **ELM** `e3sm.exe` (27 MB) — E3SM land model with ESMF include path fix
- **OpenFOAM** `foamRun` + 104 shared libs — Naming convention fix, cavity test passed
- Analytic reimplementation count: **15 → 10**

### New: Distributed Bengbu Runs (Real Binaries on Real Grid)
- **Noah-MP HRLDAS**: Real binary ran 4,018 days on 185-cell 0.25° grid (uncalibrated r=0.84)
- **tRIBS v5.3.0**: Real binary on 383-node TIN mesh (uncalibrated NSE=0.49, r=0.77)

### New: 5 Stub Models Completed (50/55 → 55/55)
- KINEROS2 (NSE=0.73), LPJ-GUESS (GPP R=0.98), QUINCY (GPP R=0.98), VELMA (NSE=0.80), WASP (Temp R=0.89)
- Each got full `ki/tools/` infrastructure (~19K lines total, validate-process-validate pattern)

### New: Validation Infrastructure
- **127 validation sheets** in standardized template (7 new + 89 updated)
- **KI_MASTER_STATUS.md** — Full inventory of all 97 models with domain, tier, metrics, test case
- **Binary audit** — Categorized all 97 models: 45 real binaries, 27 Python packages, 10 analytic

### Fixed: CMFD Unit Documentation
- **Root cause of #1 silent error found and fixed**: CMFD daily precipitation documented as `mm/day` but actual NetCDF attribute is `kg/m2/s` (factor 86400x difference)
- Fixed in: `server_datasets.yaml`, `cli_agent.py`, `PREFLIGHT.md`
- Added per-model conversion matrix (8+ different target units across models)

### Changed: Pipeline Policy ("Real Binary First")
- `cli_agent.py` Phase 3: Build is now **mandatory**, not optional. No silent Python fallback.
- `run_revalidation_55.py`: Added MODEL EXECUTION POLICY block
- `VALIDATION_PROTOCOL.md`: Added anti-patterns #6 (no Python surrogates) and #7 (no lumped when distributed possible)
- `VALIDATION_PROTOCOL.md`: Added mandatory cal/val split section with standard periods

### Changed: Data-Aware Dissection Prompts
- Agents now get data source selection guidance (CMFD vs MSWX vs ERA5 vs FLUXNET)
- Agents instructed to ALWAYS verify units from actual NetCDF attributes, never trust documentation
- PREFLIGHT section added to dissection prompt with data awareness rules

### Audits Performed
- **CMFD unit audit**: All 97 models checked — 2 bugs found and fixed (VELMA, old HydroCNHS script)
- **Per-model target unit audit**: Verified conversion factors match each model's expected input units
- **Bengbu eligibility audit**: Found 4 models that should have run Bengbu but didn't (Noah_MP, CLASSIC, ELM, tRIBS — all now completed)
- **Cross-KI synthesis** (5 parallel agents):
  - Unit traps: 650+ diagnostic triplets analyzed, top 20 universal traps identified
  - Tool patterns: 435 scripts analyzed, reusable components identified → led to ki_tools_common
  - SKILL.md patterns: 45 docs analyzed, coupling matrix and data requirements mapped
  - Validation approaches: Data leakage found in 7 models, quality tiers established
  - Build/dependency patterns: 30.3M LOC, gateway dependencies ranked

---

## v3.0 (2026-03-27) — "Auto-Dissect at Scale"

- Consolidated v1/v2 into unified `auto_dissect/` package
- 97 models auto-dissected with CLI agent pipeline
- Domain-specific validation protocols
- Data registry with 50+ datasets
- Batch processing via `run_batch.py` and `run_revalidation_55.py`

## v2.0 (2026-03-25) — "Domain Expansion"

- Extended beyond hydrology to 15 domains
- Added FLUXNET, SNOTEL, WQP, BedMachine observation data
- Domain-specific prompts and validation protocols

## v1.0 (2026-03-22) — "Foundation"

- Initial dissection pipeline for hydrology models
- Bengbu basin as standard test case
- CMFD forcing integration
- VALIDATION_PROTOCOL.md established
