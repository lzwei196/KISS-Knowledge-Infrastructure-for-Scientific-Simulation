# ParFlow Workflow — Agent-Readable Pipeline

## Pipeline Overview

ParFlow solves integrated surface-subsurface hydrology as a single coupled system.
The pipeline takes a basin shapefile + DEM + forcing data and produces:
- Discharge hydrograph at outlet
- 3D water table depth maps
- Soil moisture profiles
- Overland flow / ponding depth

## Stage Dependency Graph

```
S0 Config
   |
   v
S1 Domain/Grid
   |
   +-------+-------+
   |       |       |
   v       v       v
S2 Sub   S3 Topo  S4 CLM  (parallel)
   |       |       |
   +---+---+       |
       |           |
       v           v
   S6 IC/BC    S5 Forcing
       |           |
       +-----+-----+
             |
             v
         S7 Solver
             |
             v
         S8 Execute
             |
             v
         S9 Output
             |
             v
        S10 Coupling (optional: -> CaMa-Flood)
```

## Stage Details

### S0: Configuration (manual)
- Choose basin, period, resolution, CLM on/off
- Select forcing: CMFD (China) or MSWX (global)
- Decide MPI topology (P x Q x R)

### S1: Domain and Grid
- Tool: `define_parflow_domain.py` -> domain_definition.json
- Tool: `build_domain_mask.py` -> domain_mask.npy, surface_mask.npy
- Milestone: NX, NY, NZ defined in UTM meters, mask created

### S2: Subsurface Properties (parallel with S3, S4)
- Tool: `build_subsurface_properties.py` -> K, porosity, alpha, n arrays
- Tool: `build_mannings.py` -> Manning's n array
- **CRITICAL**: K in m/hr (NOT m/day), alpha in 1/m (NOT 1/cm)
- Milestone: All property arrays match grid dimensions

### S3: Topography (parallel with S2, S4)
- Tool: `build_slopes.py` -> slope_x.npy, slope_y.npy, elevation.npy
- **CRITICAL**: Sinks must be filled, minimum slope enforced
- Milestone: No NaN in slopes, sinks filled

### S4: CLM Setup (parallel with S2, S3)
- Tool: `setup_clm_driver.py` -> drv_clmin.dat, drv_vegm.dat, drv_vegp.dat
- Milestone: Vegetation types are realistic (IGBP 1-14, not all zeros)

### S5: Forcing (depends on S1, S4)
- Tool: `convert_forcing_to_pfb.py` -> NLDAS.*.pfb files
- **CRITICAL**: Precipitation in mm/s (NOT mm/hr), Temperature in K (NOT C)
- Milestone: Correct number of forcing files, sequential numbering

### S6: Initial/Boundary Conditions (depends on S1, S2, S3)
- Tool: `generate_initial_conditions.py` -> initial_pressure.pfb
- Milestone: Pressure field has realistic values (-100 to +50 m)

### S7: Solver Configuration (depends on all upstream)
- Tool: `generate_parflow_script.py` -> run_<name>.py
- Milestone: Script generated, P*Q*R matches nprocs

### S8: Execution (depends on S7)
- Tool: `run_parflow.py` -> PFB output files
- Expected runtime: minutes (test) to days (large basin)
- Milestone: Exit code 0, pressure + saturation PFB files exist

### S9: Output Processing (depends on S8)
- Tool: `parse_parflow_output.py` -> timeseries.json, maps
- Milestone: Water table depth and discharge extracted

### S10: Coupling (optional, depends on S9)
- Tool: `parflow_to_cama.py` -> CaMa-Flood input NetCDF
- **CRITICAL**: Do NOT also use VIC runoff for same basin (double-counting)

## Coverage Summary

| Stage | Tools | Skill Doc | Triplets |
|-------|-------|-----------|----------|
| S1 | 2 | Yes | 2 (dt_pf_013, dt_pf_014) |
| S2 | 2 | Yes | 3 (dt_pf_001, dt_pf_005, dt_pf_022) |
| S3 | 1 | Yes | 3 (dt_pf_010, dt_pf_011, dt_pf_012) |
| S4 | 1 | Yes | 1 (dt_pf_030) |
| S5 | 1 | Yes | 4 (dt_pf_002, dt_pf_003, dt_pf_006, dt_pf_007) |
| S6 | 1 | Yes | 1 (dt_pf_004) |
| S7 | 1 | Yes | 1 (dt_pf_023) |
| S8 | 1 | Yes | 3 (dt_pf_020, dt_pf_021, dt_pf_023) |
| S9 | 1 | Yes | 3 (dt_pf_040, dt_pf_041, dt_pf_042) |
| S10 | 1 | - | 3 (dt_pf_050, dt_pf_051, dt_pf_052) |
| **Total** | **12** | **9** | **25** |
