# SUMMA Knowledge Infrastructure -- Capability Inventory (KDT v5.0)

**Date**: 2026-04-03
**Model**: SUMMA (Structure for Unifying Multiple Modeling Alternatives)
**KI Version**: hydrocraft-summa v1.0.0
**Unique Value Proposition**: Multi-physics -- user selects process representations from a menu of 35 decision categories

---

## 1. Pipeline Coverage

| Stage | Name | Tools | Status | Notes |
|-------|------|-------|--------|-------|
| s1 | Domain Setup | `create_gru_hru.py`, `create_local_attributes.py` | COMPLETE | GRU/HRU from shapefile+DEM+landcover+soil |
| s2 | Forcing Prep | `build_summa_forcing_from_reanalysis.py` | COMPLETE | Forcing source (cmfd / nasa_power / mswx, via the shared loader) -> SUMMA NetCDF with unit conversions |
| s3 | Decisions | `configure_decisions.py` | COMPLETE | Full 35-category decision catalog with validation |
| s4 | Parameters | `set_trial_parameters.py` | COMPLETE | 27 parameter ranges documented with units |
| s5 | Initial Conditions | `create_initial_conditions.py` | COMPLETE | Cold-start state generation |
| s6 | Execution | `create_file_manager.py`, `validate_file_manager.py`, `run_summa.py`, `parse_summa_output.py` | COMPLETE | Full execution chain with STOP code interpretation |
| s7 | Physics Comparison | `compare_physics.py`, `plot_summa_results.py` | COMPLETE | Automated multi-variant runs and comparison |

**Tool count**: 12 tools across all 7 stages (all present)
**Skill documents**: 7 of 7 exist and are populated (plus phase2_knowledge_classification.md)
**Diagnostic triplets**: 18 (covering 7 failure domains, 5 silent errors = 28%)

---

## 2. Unique Capability Assessment: Multi-Physics

### Is multi-physics actually exploited in the KI?

**YES, comprehensively.** The KI exploits multi-physics at three levels:

1. **s3_decisions/configure_decisions.py** -- Contains the COMPLETE decision catalog (35 categories) with:
   - All valid options per category (e.g., 5 options for `canopySrad`, 4 for `snowDenNew`)
   - Known incompatible combinations (4 documented incompatibilities)
   - Safe default decision set (34 decisions pre-configured)
   - Input validation against the catalog
   - Grouped output by category for readability

2. **s7_physics_comparison/compare_physics.py** -- Automates the multi-physics workflow:
   - Takes a decision variation dictionary (e.g., `{"snowLayers": ["jrdn1991", "CLM_2010"]}`)
   - Generates full factorial combinations
   - Creates modified decisions files and fileManager for each variant
   - Runs SUMMA for each combination
   - Extracts statistics (mean, std, max) for comparison variables
   - Outputs `physics_comparison.csv`

3. **Skill document s7** -- Documents 4 recommended comparison experiments:
   - Snow physics (8 variants), stomatal resistance (6 variants), runoff generation (6 variants), radiation transfer (3 variants)

### What IS exploited:

| Multi-physics capability | Status | Quality |
|--------------------------|--------|---------|
| Decision catalog (all valid options) | COMPLETE | Derived from mDecisions.f90 source |
| Incompatibility checking | PARTIAL | 4 rules documented; more exist in SUMMA |
| Default decision set | COMPLETE | 34 decisions, scientifically reasonable |
| Automated variant comparison | COMPLETE | Full factorial with output statistics |
| Basin-type decision recommendations | COMPLETE | Snow-dominated, humid-forested, semi-arid |
| Plotting comparison results | COMPLETE | plot_summa_results.py with multi-panel figures |

### What is NOT exploited:

| Multi-physics capability | Status | Impact |
|--------------------------|--------|--------|
| Calibration (parameter optimization) | NOT IMPLEMENTED | No tool to optimize parameters for a given decision set |
| Decision sensitivity ranking | NOT IMPLEMENTED | No tool to rank which decision has most impact |
| Ensemble prediction (all-decisions spread) | NOT IMPLEMENTED | Cannot quantify total structural uncertainty |
| Adaptive decision selection | NOT IMPLEMENTED | No tool to auto-select best physics for a basin type |
| Observation-based decision validation | NOT IMPLEMENTED | Cannot use obs Q/ET/SWE to select best physics |

### Verdict: Multi-physics is WELL EXPLOITED for exploration, WEAK for optimization

The KI enables systematic comparison of physics options (the core SUMMA value), but cannot determine which physics are BEST for a given basin because there is no calibration tool and no observation-based validation of physics choices.

---

## 3. Physics Options: Complete Catalog

The `configure_decisions.py` tool documents ALL 35 decision categories. Summary of option counts:

| Category | Decisions | Total Options | Notes |
|----------|-----------|---------------|-------|
| Soil/veg tables | 2 | 5 | STAS, STAS-RUC, ROSETTA for soil |
| Stomatal resistance | 2 | 8 | BallBerry, Jarvis, simpleResistance + variants |
| Ball-Berry sub-options | 7 | 16 | Only active when stomResist=BallBerry |
| Numerical methods | 2 | 5 | itertive (robust), itersurf (fast) |
| LAI | 1 | 2 | Monthly table or specified |
| Canopy | 3 | 10 | Interception, emission, shortwave radiation |
| Soil water | 4 | 10 | Richards equation, groundwater, conductivity |
| Boundary conditions | 4 | 11 | Upper/lower, thermal/hydraulic |
| Vegetation | 2 | 5 | Traits, root profile |
| Snow | 8 | 21 | Layer management, compaction, density, albedo |
| Spatial structure | 2 | 4 | Groundwater connectivity, routing |
| **Total** | **35** | **~97** | |

All options are documented in the tool and validated against SUMMA source code. The KI correctly handles SUMMA's abbreviated spellings (`itertive`, `numericl`, `consettl`).

---

## 4. Global Applicability

| Dimension | Status | Evidence |
|-----------|--------|----------|
| Forcing: direct from the source | COMPLETE | `build_summa_forcing_from_reanalysis.py --source cmfd|nasa_power|mswx` (shared loader); lapse correction against a reference elevation |
| Forcing: other datasets (ERA5, a station) | NOT SUPPORTED | No reader; the loader would have to learn the dataset first |
| Domain: Any shapefile | COMPLETE | `create_gru_hru.py` works with any shapefile + DEM |
| Soil: STATSGO (STAS) tables | COMPLETE | Hardcoded in SUMMA lookup tables |
| Soil: ROSETTA pedotransfer | AVAILABLE | Decision option exists but not tested |
| Land cover: MODIS IGBP | COMPLETE | `MODIFIED_IGBP_MODIS_NOAH` as default |
| Land cover: USGS | AVAILABLE | Decision option exists |
| Gauge: Generic | COMPLETE | HRU-based, no specific gauge system dependency |

**Assessment**: SUMMA's domain setup is globally applicable (any shapefile + DEM + landcover + soil raster). The forcing tool reads the source directly: CMFD for China, NASA POWER (from 2001) and MSWX (from 1979) elsewhere. MSWX is slow for many HRUs (about 20 minutes per HRU location and year). [Updated 2026-10-02; the earlier text said forcing could only come from another model's forcing files.]

---

## 5. Known Performance Baseline

| Basin | Country | NSE | Notes |
|-------|---------|-----|-------|
| Belly River | Canada | 0.147 | Uncalibrated, default parameters, default decisions |

Only one basin tested. NSE=0.147 is poor but expected for uncalibrated SUMMA with default parameters. SUMMA typically requires parameter calibration to achieve NSE > 0.5.

---

## 6. Gaps and Weaknesses

### CRITICAL GAPS

1. **No calibration tool** -- SUMMA has no built-in optimizer (unlike mHM). External calibration (e.g., Ostrich, MOCOM-UA) is standard practice but no KI tool wraps this. Without calibration, SUMMA cannot produce scientifically useful predictions (NSE=0.147 is not useful).

2. **Forcing sources are three** -- CMFD, NASA POWER and MSWX through the shared loader. ERA5 or station data have no reader yet. MSWX point reads are slow for many-HRU domains (no many-point sub-daily reader for it).

### MODERATE GAPS

3. **No observation-based physics selection** -- The compare_physics tool runs variants and computes output statistics, but does not compare against observations. It cannot answer "which physics option best matches observed streamflow?"

4. **Reference elevation for lapse correction** -- CMFD has its own elevation field; for NASA POWER and MSWX the cell elevation must be given as one number (`--reference_elev_m`) or the build stated as `--no_lapse`.

5. **Incomplete incompatibility rules** -- Only 4 decision incompatibilities documented. SUMMA has more (e.g., certain canopySrad options require specific LAI_method). A comprehensive incompatibility matrix would prevent runtime crashes.

### MINOR GAPS

6. **No restart/warm-start workflow** -- The KI creates cold-start initial conditions but does not document how to use SUMMA's restart capability to avoid re-spinning up for variant runs.

7. **No multi-GRU routing** -- `subRouting` options (timeDlay, qInstant) are simple; no coupling to external routing models (CaMa-Flood, mizuRoute) is implemented.

8. **CRS validation missing** -- dt_018 documents the CRS mismatch silent error, but `create_gru_hru.py` does not actually check CRS consistency between shapefile and DEM.

---

## 7. Recommendation

### LEAVE AS-IS (with minor fixes)

SUMMA's multi-physics capability is well-exploited in the KI. The decision catalog is complete, the comparison workflow is automated, and the skill documents provide clear guidance. The KI delivers on SUMMA's unique value proposition.

**Rationale for not expanding now**:

- SUMMA's primary value (multi-physics comparison) is FULLY IMPLEMENTED
- Calibration would improve performance but is a major effort (external optimizer integration) and lower priority than fixing mHM's calibration gap
- A head-to-head comparison with another model is done by naming the same forcing source for both, each through its own KI tool
- Only 1 basin tested (Belly River), but the tools are basin-agnostic

**Minor fixes recommended** (not full expansion):

1. **Add CRS check to create_gru_hru.py** (LOW effort) -- Assert that shapefile and DEM CRS match, preventing the dt_018 silent error.

2. **Add observation comparison to compare_physics.py** (MEDIUM effort) -- Accept an optional observed streamflow file and compute NSE/KGE for each physics variant. This is a natural extension of the existing comparison workflow.

3. **Document restart workflow** (LOW effort) -- Add a note to s6_execution_skill.md about saving/loading restart files for efficient variant runs.

**If expansion is later prioritized**:

4. **Many-point sub-daily reader for MSWX / NASA POWER** (MEDIUM effort, in the shared loader) -- would make multi-HRU builds outside China fast.

5. **Calibration tool wrapping Ostrich/MOCOM-UA** (HIGH effort) -- Would enable scientifically useful predictions. Consider this only after mHM calibration is addressed first.

---

## 8. Comparison: mHM vs SUMMA KI Maturity

| Dimension | mHM | SUMMA | Winner |
|-----------|-----|-------|--------|
| Pipeline completeness | 9/11 stages (s9, docs missing) | 7/7 stages (all present) | SUMMA |
| Unique capability exploitation | MPR structurally present but operationally weak (no calibration) | Multi-physics fully implemented | SUMMA |
| Skill documents | 0/10 exist | 7/7 exist | SUMMA |
| Diagnostic triplets | 26 (3 validated) | 18 (0 validated) | mHM (more battle-tested) |
| Tested basins | 2 (Mosel, Bengbu) + Wangjiaba data KIs | 1 (Belly River) | mHM |
| Performance achieved | NSE=0.77 (Mosel, tuned) | NSE=0.147 (Belly River, uncalibrated) | mHM |
| Global readiness | Global L0 data; forcing from CMFD (China), NASA POWER or MSWX (global) | MSWX slow for many HRUs | mHM |
| Tool quality | 2 known bugs (slope, metrics) | 1 known gap (CRS check) | SUMMA |

**Summary**: SUMMA has a more complete and polished KI structure, but mHM has been tested on more basins and has more diagnostic experience. Both lack calibration tools, which is the single biggest barrier to scientific utility. mHM should be expanded first (calibration unlocks MPR), then SUMMA calibration as a follow-up.

---

*Generated by KDT v5.0 Capability Discovery | 2026-04-03*
