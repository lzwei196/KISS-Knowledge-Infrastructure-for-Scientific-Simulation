# Phase 2: Knowledge Classification -- CRHM

## s1_basin_setup: HRU Delineation

| Knowledge Item | Type | Source |
|---------------|------|--------|
| DEM clipping to basin boundary | Procedural | Code (rasterio.mask) |
| Elevation band computation | Procedural | Code (numpy quantiles) |
| Land cover cross-tabulation | Procedural | Code (numpy unique) |
| HRU count selection (3-30) | Evaluative | Expert judgment |
| Aspect stratification for mountains | Evaluative | Cold regions domain knowledge |
| Fetch distance assignment by land cover | Evaluative | PBSM literature |
| CRS mismatch detection | Debugging | Experience (dt_012) |
| Too many HRUs for small basin | Debugging | Experience |

## s2_observation_data: Obs File Preparation

| Knowledge Item | Type | Source |
|---------------|------|--------|
| Specific humidity to relative humidity conversion | Procedural | Tetens formula |
| Precipitation rate conversion (mm/timestep to mm/d) | Procedural | Unit arithmetic |
| .obs header format generation | Procedural | CRHM format spec |
| Computed variable ($) formula syntax | Procedural | CRHM format spec |
| **Humidity unit detection (0-1 vs 0-100)** | **Debugging (CRITICAL)** | Experience (dt_001) |
| Winter gap detection and filling strategy | Evaluative | Cold regions domain |
| Station reliability assessment in extreme cold | Evaluative | Operational experience |
| Reanalysis vs station data tradeoff | Evaluative | Expert judgment |

## s3_module_selection: Module Chain

| Knowledge Item | Type | Source |
|---------------|------|--------|
| Module dependency resolution (declgetvar chain) | Procedural | CRHM source code |
| Module ordering algorithm | Procedural | Topological sort |
| Prairie vs mountain vs forest landscape assessment | Evaluative | Geomorphology |
| PBSM applicability (wind-exposed only) | Evaluative | Pomeroy et al. literature |
| PrairieInfil limitation (clay soils only) | Evaluative | Gray et al. literature |
| Slope_Qsi necessity for mountainous terrain | Evaluative | Radiation physics |
| Wrong module for landscape (silent error) | Debugging | Experience (dt_016) |

## s4_parameter_config: .prj Parameters

| Knowledge Item | Type | Source |
|---------------|------|--------|
| .prj section generation with ###### delimiters | Procedural | CRHM format spec |
| Parameter value formatting (space-separated) | Procedural | CRHM format spec |
| Fetch distance calibration by land cover | Evaluative | PBSM literature |
| Vegetation height estimation | Evaluative | Land cover databases |
| Fall moisture condition for PrairieInfil | Evaluative | Antecedent conditions |
| **Silent parameter clamping detection** | **Debugging (CRITICAL)** | Experience (dt_006) |
| Parameter count vs nhru mismatch | Debugging | Experience (dt_005) |

## s5_execution: CRHM Run

| Knowledge Item | Type | Source |
|---------------|------|--------|
| CLI invocation with flags | Procedural | CRHM --help |
| Output parsing (skip row 2 units) | Procedural | Code / format spec |
| CSV/NetCDF conversion | Procedural | Code (pandas, xarray) |
| Obs file path resolution (CWD vs .prj dir) | Debugging | Experience (dt_007) |
| Empty output with exit code 0 | Debugging | Experience (dt_014) |
| Boost library runtime linking | Debugging | Experience (dt_017) |
| SWE seasonal cycle sanity check | Evaluative | Hydrology domain |

## s6_vic_coupling: VIC-CRHM Integration

| Knowledge Item | Type | Source |
|---------------|------|--------|
| VIC forcing to .obs conversion | Procedural | Tool (convert_vic_to_obs) |
| Temporal resampling (sub-daily to daily) | Procedural | Code (pandas resample) |
| Area-weighted HRU-to-grid aggregation | Procedural | Spatial math |
| **Process ownership table definition** | **Evaluative (CRITICAL)** | Coupling design |
| **Double-counting detection** | **Debugging (CRITICAL)** | Experience (dt_010) |
| Spatial interpolation method (area-weighted, not bilinear) | Evaluative | Conservation physics |
| Diagnostic interpretation (CRHM informs VIC calibration) | Evaluative | Expert judgment |

---

**High-priority "experience-only" items** (flagged for detailed extraction):
1. Humidity unit detection (dt_001) -- #1 silent error
2. Silent parameter clamping (dt_006) -- model gives no warning
3. Process ownership in coupling (dt_010) -- must be defined before any merge
4. Winter gap-filled data quality (dt_011) -- station data unreliable in extreme cold
5. Wrong module for landscape (dt_016) -- PBSM in forest, no Slope_Qsi in mountains
