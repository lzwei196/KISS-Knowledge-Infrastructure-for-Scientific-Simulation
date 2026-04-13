# Phase 2: Knowledge Classification -- SUMMA

## s1_domain_setup

| Knowledge Item | Type | Source |
|---------------|------|--------|
| Grid cells = GRUs, unique soil/veg combos = HRUs | Procedural | SUMMA docs |
| CRS must match across shapefile, DEM, land cover, soil rasters | Evaluative | Cross-model experience (cm_012) |
| Basin edge cells may have partial coverage -> missing forcing | Debugging | Operational experience |
| HRU IDs must be consistent across ALL NetCDF files | Evaluative | SUMMA source (summaFileManager.f90) |
| Land cover classification must match vegeParTbl decision | Evaluative | Domain knowledge |

## s2_forcing_prep

| Knowledge Item | Type | Source |
|---------------|------|--------|
| VIC precip mm/timestep -> SUMMA kg/m2/s: divide by DATA_STEP | Procedural | Unit analysis |
| VIC temp C -> SUMMA K: add 273.15 | Procedural | Unit analysis |
| VIC pressure kPa -> SUMMA Pa: multiply by 1000 | Procedural | Unit analysis |
| Forcing hruId must match attributes hruId exactly | Evaluative | SUMMA source |
| Mean pptrate should be ~1e-5 kg/m2/s for temperate basins | Debugging | Empirical validation |
| Pressure in wrong units causes NaN soil temperature | Debugging | Operational experience |
| **Experience-only**: "You just know if the precip looks right" | HIGH PRIORITY | Practitioner interview |

## s3_decisions

| Knowledge Item | Type | Source |
|---------------|------|--------|
| 35 decision categories with specific valid options | Procedural | mDecisions.f90 |
| Some options use intentional abbreviations (itertive, numericl) | Debugging | Source code analysis |
| Ball-Berry sub-options ignored when stomResist != BallBerry | Evaluative | Source code logic |
| f_Richards=moisture incompatible with bcLowrSoiH=presHead | Evaluative | Numerical analysis |
| CLM_2010 snow layers are generally more robust than jrdn1991 | Evaluative | Literature review |
| **Experience-only**: "Which combinations work for which basins" | HIGH PRIORITY | Practitioner interview |

## s4_parameters

| Knowledge Item | Type | Source |
|---------------|------|--------|
| Trial params override lookup table defaults | Procedural | SUMMA docs |
| Parameter names are case-sensitive and specific (k_soil not ksat) | Debugging | Operational experience |
| Unknown parameter names are silently ignored | Debugging | Source code analysis |
| theta_res must be < theta_sat | Evaluative | Soil physics |
| k_soil range 1e-8 to 1e-2 m/s covers most soil types | Evaluative | Soil science literature |

## s5_initial_conditions

| Knowledge Item | Type | Source |
|---------------|------|--------|
| Default 8 soil layers: [0.025, 0.075, 0.15, 0.25, 0.50, 0.50, 1.0, 1.5] m | Procedural | SUMMA conventions |
| nSoil in coldState must match model config exactly | Debugging | Runtime crashes |
| Cold start needs 1-2 year spinup (5+ for groundwater basins) | Evaluative | Hydrologic modeling experience |
| Initial moisture at field capacity (~0.30) reduces spinup time | Evaluative | Practitioner experience |
| **Experience-only**: "You need to throw away the first year" | HIGH PRIORITY | Universal among hydrologists |

## s6_execution

| Knowledge Item | Type | Source |
|---------------|------|--------|
| fileManager.txt must have controlVersion SUMMA_FILE_MANAGER_V3.0.0 | Procedural | SUMMA source |
| ALL paths must be absolute (Fortran CWD resolution) | Evaluative | Fortran trap cm_008 |
| Paths must end with / for directories | Procedural | SUMMA source |
| Path length < 256 chars (CHARACTER limit) | Debugging | Fortran trap cm_008 |
| STOP 10 = file I/O, STOP 20 = NetCDF, STOP 30 = decision, STOP 40 = convergence | Debugging | Source code analysis |
| Convergence failure: reduce time step, check forcing quality, try itertive solver | Debugging | Operational experience |
| Zero runoff output: usually precipitation unit conversion error | Debugging | Operational experience |

## s7_physics_comparison

| Knowledge Item | Type | Source |
|---------------|------|--------|
| Each variant needs its own decisions file referenced by its own fileManager | Procedural | SUMMA architecture |
| Identical results = decisions file was not actually changed | Debugging | Operational experience |
| Full factorial with >5 decisions produces too many variants | Evaluative | Computational cost |
| One-at-a-time sensitivity first, then 2-way interactions | Evaluative | Experimental design |
| Each variant needs independent spinup period | Evaluative | Hydrologic modeling experience |
