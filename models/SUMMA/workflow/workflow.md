# SUMMA Workflow -- Agent-Readable Pipeline Document

## Pipeline Overview

SUMMA (Structure for Unifying Multiple Modeling Alternatives) is a multi-physics hydrologic framework. The pipeline has 7 stages that transform geospatial and meteorological data into hydrologic simulations with configurable physics options.

```
[Basin Shapefile + DEM + Land Cover + Soil Type]
        |
        v
  s1: Domain Setup (GRU/HRU) -----> attributes.nc
        |                              |
        |     [VIC Forcing Files]      |
        |            |                 |
        v            v                 |
  s2: Forcing Prep -----> forcing_YYYY.nc
        |                              |
  s3: Decisions (independent) --> decisions.txt
        |                              |
        v                              |
  s4: Parameters -----------> trialParams.nc
        |                              |
        v                              |
  s5: Initial Conditions ----> coldState.nc
        |                              |
        v                              v
  s6: Execution (fileManager.txt + summa.exe)
        |
        v
    SUMMA Output NetCDF
        |
        v
  s7: Physics Comparison (multiple runs)
        |
        v
    Comparison CSV + Plots
```

## Stage Details

### s1_domain_setup (Order: 1)
**Purpose**: Define GRU/HRU spatial structure from geospatial data.
**Tools**: create_gru_hru, create_local_attributes
**Output**: attributes.nc (NetCDF with gruId, hruId, lat, lon, elevation, area, slope, veg/soil indices)
**Milestone**: attributes.nc has hru and gru dimensions
**Depends on**: nothing
**Skill doc**: docs/s1_domain_setup_skill.md
**Key triplets**: dt_010 (ID inconsistency), dt_018 (CRS mismatch)

### s2_forcing_prep (Order: 2)
**Purpose**: Convert meteorological forcing to SUMMA NetCDF format with correct units.
**Tools**: convert_vic_forcing_to_summa
**Output**: forcing_YYYY.nc (one per year, 7 variables: pptrate, airtemp, SWRadAtm, LWRadAtm, windspd, airpres, spechum)
**Milestone**: All 7 variables present with correct units
**Depends on**: s1_domain_setup (needs attributes.nc for hruId)
**Skill doc**: docs/s2_forcing_prep_skill.md
**Key triplets**: dt_003 (precip units), dt_004 (pressure units), dt_005 (hruId mismatch), dt_012 (ET wrong)

### s3_decisions (Order: 3)
**Purpose**: Configure model physics options (SUMMA's unique feature).
**Tools**: configure_decisions
**Output**: decisions.txt (35 keyword-option pairs)
**Milestone**: All decisions have valid options
**Depends on**: nothing (can run in parallel with s1/s2)
**Skill doc**: docs/s3_decisions_skill.md
**Key triplets**: dt_009 (invalid option -> STOP 30)

### s4_parameters (Order: 4)
**Purpose**: Set site-specific parameters overriding lookup table defaults.
**Tools**: set_trial_parameters
**Output**: trialParams.nc (per-HRU parameter values)
**Milestone**: NetCDF has hru dimension matching attributes
**Depends on**: s1_domain_setup, s3_decisions
**Skill doc**: docs/s4_parameters_skill.md
**Key triplets**: dt_014 (params silently ignored)

### s5_initial_conditions (Order: 5)
**Purpose**: Generate cold-start initial state for snow, soil, canopy, aquifer.
**Tools**: create_initial_conditions
**Output**: coldState.nc (state variables for nSoil layers)
**Milestone**: All required state variables present, nSoil matches config
**Depends on**: s1_domain_setup, s4_parameters
**Skill doc**: docs/s5_initial_conditions_skill.md
**Key triplets**: dt_006 (layer mismatch), dt_015 (spinup artifacts)

### s6_execution (Order: 6)
**Purpose**: Generate fileManager.txt, validate, run SUMMA, parse output.
**Tools**: create_file_manager, validate_file_manager, run_summa, parse_summa_output
**Output**: SUMMA output NetCDF (runoff, ET, SWE, soil moisture, energy fluxes)
**Milestone**: Exit code 0, output has time dimension > 0
**Depends on**: ALL previous stages
**Skill doc**: docs/s6_execution_skill.md
**Key triplets**: dt_001 (missing file), dt_002 (path truncation), dt_007 (convergence), dt_008 (NetCDF error), dt_011 (zero runoff), dt_013 (NaN), dt_016 (library)

### s7_physics_comparison (Order: 7)
**Purpose**: Run multiple decision combinations and compare results.
**Tools**: compare_physics, plot_summa_results
**Output**: physics_comparison.csv, comparison plots
**Milestone**: All variants completed, results differ
**Depends on**: s6_execution
**Skill doc**: docs/s7_physics_comparison_skill.md
**Key triplets**: dt_017 (identical results)

## Coverage Summary

| Category | Count |
|----------|-------|
| Pipeline stages | 7 |
| Validated tools | 12 |
| Skill documents | 7 |
| Diagnostic triplets | 18 |
| Failure domains | 7 (path_resolution, unit_conversion, dependency_mismatch, parameter_format, runtime, silent_error, environment) |
| Silent errors | 5 (28%) |
| Fatal errors | 10 (56%) |
