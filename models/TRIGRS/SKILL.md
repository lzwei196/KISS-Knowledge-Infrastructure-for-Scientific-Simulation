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
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (22 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_rainfall_to_trigrs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_rainfall_to_trigrs.py --help` |
| `tools/convert_soil_to_trigrs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_to_trigrs.py --help` |
| `tools/generate_tr_in.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_tr_in.py --help` |
| `tools/parse_trigrs_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_trigrs_output.py --help` |
| `tools/run_trigrs.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_trigrs.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# TRIGRS v2.1 (Transient Rainfall Infiltration and Grid-Based Regional Slope-Stability) --- Knowledge Infrastructure

**Package**: `hydrocraft-trigrs-landslide` v1.0.0
**Model**: TRIGRS v2.1.00c (serial) + MPI parallel version
**Source**: USGS (Rex L. Baum & Massimiliano Alvioli)
**Last updated**: 2026-03-26
**Stats**: 5 tools | 6 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `tutorial_validated` (USGS tutorial dataset, Srivastava-Yeh column test)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for meteorological forcing documentation.
See `data_ki/USGS_Sediment/SKILL.md` for suspended sediment observations.


## Overview

This knowledge infrastructure enables autonomous simulation of rainfall-induced shallow landslide susceptibility using TRIGRS (Transient Rainfall Infiltration and Grid-Based Regional Slope-Stability Analysis). The 5 validated tools replace the manual GIS + command-line TRIGRS workflow with a Python pipeline that automates grid preparation, parameter assignment, execution, and output parsing.

**What TRIGRS does**: Cell-by-cell transient pore-pressure and infinite-slope factor-of-safety model. Simulates:
- Transient rainfall infiltration using analytical solutions (1D vertical flow)
- Saturated-zone infiltration (Iverson, 2000; Savage et al., 2003)
- Unsaturated-zone infiltration (Srivastava & Yeh, 1991)
- Finite-depth and infinite-depth soil column options
- Pore-pressure response at multiple depths within each cell
- Factor of safety (FS) using infinite-slope stability analysis
- Surface runoff routing (D8 flow direction, optional)
- Mass balance tracking

**Key difference from other landslide models**: TRIGRS uses analytical (closed-form) solutions for transient infiltration rather than numerical PDE solvers. This makes it fast for regional-scale analysis but restricts it to 1D vertical flow in homogeneous, isotropic layers per cell.

---

## Installation

### Binary (compile from Fortran source)

```
Serial:    src/TRIGRS/ -> make trg   (produces ./trg)
Parallel:  src/TRIGRS/ -> make prg   (produces ./prg, requires MPI)
TopoIndex: src/TopoIndex/ -> make tpx (produces ./tpx)
```

### Compiler requirements

```
Fortran 95/77:  gfortran (GCC) or any F95-compliant compiler
MPI (parallel): OpenMPI or MPICH (libopenmpi-dev on Ubuntu)
Libraries:      libgsl-dev, libgslcblas (optional, for GSL math)
```

### Companion utilities

```
TopoIndex:    Computes flow directions, weighting factors, grid dimensions
GridMatch:    Verifies grid congruence (rows, cols, nodata alignment)
UnitConvert:  Applies scalar conversion factor to grid values
```

### Test example

```
data/tutorial/         # 10x10 grid, 2 zones, 2 rainfall periods
  dem.asc              # Digital elevation model (ESRI ASCII grid)
  slope.asc            # Slope angle grid (degrees)
  zones.asc            # Property zone grid (integer zone IDs)
  zmax.asc             # Maximum soil depth grid (meters)
  depthwt.asc          # Initial water table depth (meters)
  rizero.asc           # Initial steady infiltration rate (m/s)
  ri1.asc, ri2.asc     # Rainfall intensity per period (m/s)
tr_in.txt              # Main initialization file
tpx_in.txt             # TopoIndex initialization file
```

---

## Pipeline (8 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Select study area, rainfall event, time parameters |
| 1 | DEM & slope prep | GIS / `convert_dem_to_trigrs` | Prepare DEM, slope, flow-direction ASCII grids |
| 2 | Soil parameters | `convert_soil_to_trigrs` | Assign zone-based soil properties (c, phi, Ks, D, etc.) |
| 3 | Rainfall forcing | `convert_rainfall_to_trigrs` | Convert rainfall data to intensity grids (m/s) |
| 4 | TopoIndex | `run_topoindex` (within `run_trigrs`) | Compute flow routing weights and grid dimensions |
| 5 | Init file assembly | `convert_rainfall_to_trigrs` | Generate tr_in.txt initialization file |
| 6 | Execution | `run_trigrs` | Compile (if needed), run TopoIndex + TRIGRS |
| 7 | Output parsing | `parse_trigrs_output` | Extract FS grids, pressure head, water table to CSV |

---

## Input File Format (tr_in.txt)

The TRIGRS initialization file `tr_in.txt` is a line-oriented text file where each value line is preceded by a descriptive header line. **The order of lines is fixed and must not be changed.**

### Key parameters and units

| Line | Parameter | Symbol | Unit | Description |
|------|-----------|--------|------|-------------|
| 4 | tx | tx | integer | Output time-step multiplier |
| 4 | nmax | nmax | integer | Max terms in infinite series |
| 4 | mmax | mmax | integer | Max iterations (negative = finite depth) |
| 4 | zones | nzon | integer | Number of property zones |
| 6 | nzs | nzs | integer | Number of vertical computation points |
| 6 | zmin | zmin | m | Minimum depth for computation |
| 6 | uww | uww | N/m^3 | Unit weight of water (typically 9800) |
| 6 | nper | nper | integer | Number of rainfall periods |
| 6 | t | t | **seconds** | Total simulation duration |
| 8 | zmax | zmax | **m** | Maximum depth below ground (negative = use grid) |
| 8 | depth | dep | **m** | Depth to initial water table (negative = use grid) |
| 8 | rizero | rizero | **m/s** | Initial steady infiltration rate (negative = use grid) |
| 8 | slomin | slomin | **degrees** | Minimum slope angle for computation |
| 8 | slomax | slomax | **degrees** | Maximum slope angle for computation |
| 11,14 | cohesion | c | **Pa** | Soil cohesion |
| 11,14 | phi | phi | **degrees** | Soil friction angle |
| 11,14 | uws | uws | **N/m^3** | Unit weight of soil (typically 19000-22000) |
| 11,14 | diffus | D0 | **m^2/s** | Saturated hydraulic diffusivity |
| 11,14 | K-sat | Ks | **m/s** | Saturated hydraulic conductivity |
| 11,14 | Theta-sat | ths | - | Saturated volumetric water content |
| 11,14 | Theta-res | thr | - | Residual volumetric water content |
| 11,14 | Alpha | alpha | **1/m** | Gardner soil-water parameter (negative = saturated model) |
| 16 | cri | cri | **m/s** | Rainfall intensity for each period |
| 18 | capt | capt | **seconds** | Cumulative time at start/end of each period |

---

## 8. Unit Conversion Table

**Critical**: TRIGRS is unit-sensitive and many mistakes produce plausible-looking files with wrong magnitudes. This unit table documents the pipeline conversions that must be verified before generating `tr_in.txt` or raster inputs.

| Variable | Source unit | TRIGRS unit | Conversion | Type |
|---|---|---|---|---|
| Rainfall intensity (`cri`) | mm/hr | m/s | divide by 3.6e6 | multiplicative |
| Rainfall intensity (`cri`) | mm/day | m/s | divide by 8.64e7 | multiplicative |
| Time duration (`t`, `capt`) | hours | seconds | multiply by 3600 | multiplicative |
| Cohesion (`c`) | kPa | Pa | multiply by 1000 | multiplicative |
| Unit weight water (`uww`) | kN/m^3 | N/m^3 | multiply by 1000 | multiplicative |
| Unit weight soil (`uws`) | kN/m^3 | N/m^3 | multiply by 1000 | multiplicative |
| Slope angle grid | radians | degrees | multiply by 180/pi | multiplicative |
| Depth (`zmax`, `dep`) | feet | meters | multiply by 0.3048 | multiplicative |
| K-sat | cm/hr | m/s | multiply by 2.778e-6 | multiplicative |
| Diffusivity (`D0`) | cm^2/s | m^2/s | multiply by 1e-4 | multiplicative |
| Alpha (unsaturated) | 1/cm | 1/m | multiply by 100 | multiplicative |
| DEM and slope grids | mixed CRS/cell size | same CRS/cell size | use GridMatch | validation |

---

## Unit Trap Table (CRITICAL)

These are the most dangerous unit conversion errors when setting up TRIGRS. All cause **silent** failures (wrong results, no crash).

| ID | Variable | TRIGRS expects | Common source | Trap | Impact |
|----|----------|---------------|---------------|------|--------|
| dt_001 | Rainfall intensity (cri) | **m/s** | mm/hr | Divide by 3.6e6 | 3.6M x too much rain |
| dt_002 | Rainfall intensity (cri) | **m/s** | mm/day | Divide by 8.64e7 | 86.4M x too much rain |
| dt_003 | Time duration (t, capt) | **seconds** | hours | Multiply by 3600 | Wrong event timing |
| dt_004 | Cohesion (c) | **Pa** | kPa | Multiply by 1000 | FS 1000x too high |
| dt_005 | Unit weight water (uww) | **N/m^3** | kN/m^3 | Multiply by 1000 | FS scaled wrong |
| dt_006 | Unit weight soil (uws) | **N/m^3** | kN/m^3 | Multiply by 1000 | FS scaled wrong |
| dt_007 | Slope angle grid | **degrees** | radians | Multiply by 180/pi | Wrong tan(slope) |
| dt_008 | Depth (zmax, dep) | **meters** | feet | Multiply by 0.3048 | Wrong pressure |
| dt_009 | K-sat | **m/s** | cm/hr | Multiply by 2.778e-6 | Infiltration wrong |
| dt_010 | Diffusivity (D0) | **m^2/s** | cm^2/s | Multiply by 1e-4 | Timing off |
| dt_011 | Alpha (unsaturated) | **1/m** | 1/cm | Multiply by 100 | Wrong retention |
| dt_012 | DEM & slope grids | same CRS, cell size | mixed sources | Use GridMatch | Grid mismatch crash |

---

## 6. Output Description (dag.yaml)

**Source of truth**: `dag.yaml`. The dag defines the model's observable outputs, units, and validation rank. If this section ever disagrees with `dag.yaml`, the dag wins.

**Headline output**: `minimum_factor_of_safety` is the dag's rank-1 variable and the primary variable this model is judged by.

> `minimum_factor_of_safety` — Minimum computed factor of safety in the soil column across all computation depths at each cell for a given elapsed time; Fs<1 predicts failure, Fs=1 limiting equilibrium, Fs>=1 stable. Clamped to a maximum of 10; cells below slomin assigned 11. (dimensionless)

Other dag outputs named by this KI: `depth_of_minimum_FS`, `pressure_head_at_min_FS`, `water_table_depth`, `actual_infiltration_rate`, `surface_runoff`.

| Output variable (dag `var`) | Validation role | Unit | File pattern in this KI |
|---|---|---|---|
| `minimum_factor_of_safety` | rank 1 headline output | dimensionless | `TRfs_min_SUFFIX_#.asc` |
| `depth_of_minimum_FS` | other dag output | m | `TRz_at_fs_min_SUFFIX_#.asc` |
| `pressure_head_at_min_FS` | other dag output | m | `TRp_at_fs_min_SUFFIX_#.asc` |
| `water_table_depth` | other dag output | m | `TRwater_depth_SUFFIX_#.asc` |
| `actual_infiltration_rate` | other dag output | m/s | `TRinfiltration_SUFFIX_#.asc` |
| `surface_runoff` | other dag output | m/s | `TRrunoff_SUFFIX_#.asc` |

---

## Output Files

### Grid outputs (ESRI ASCII format)

| File pattern | Content | Unit |
|---|---|---|
| TRfs_min_SUFFIX_#.asc | Minimum factor of safety | dimensionless |
| TRz_at_fs_min_SUFFIX_#.asc | Depth of minimum FS | m |
| TRp_at_fs_min_SUFFIX_#.asc | Pressure head at min FS depth | m |
| TRwater_depth_SUFFIX_#.asc | Water table depth below surface | m |
| TRwater_eleva_SUFFIX_#.asc | Water table elevation | m (datum) |
| TRinfiltration_SUFFIX_#.asc | Actual infiltration rate | m/s |
| TRrunoff_SUFFIX_#.asc | Surface runoff | m/s |

### List/profile outputs

| File pattern | Content |
|---|---|
| TRlist_z_p_fs_SUFFIX_#.txt | Depth profiles of pressure head & FS per cell |
| TR_ijz_p_th_SUFFIX_#.txt | i-j-z format for Scoops3D |
| TR_xyz_p_th_SUFFIX_#.okc | XMDV format for 3D visualization |

### Log files

| File | Content |
|---|---|
| TrigrsLog.txt | Run log with timing, convergence, mass balance |

---

## Critical Domain Knowledge

### dk_001: All times in seconds (CRITICAL)

TRIGRS expects **all temporal values in seconds**: total duration `t`, period boundaries `capt()`, and output times. A 48-hour storm requires `t = 172800`, not `t = 48`. This is the most common error for new users. **No error message** is produced if hours are entered; the simulation simply runs for the wrong duration.

### dk_002: Rainfall intensity in m/s, NOT mm/hr (CRITICAL)

Rainfall `cri()` and initial infiltration `rizero` must be in **meters per second**. A typical heavy rainfall of 20 mm/hr = 5.56e-6 m/s. If mm/hr is entered directly, infiltration will be ~3.6 million times too high, causing instant saturation and unrealistic FS values. **No error or warning** is produced.

### dk_003: Negative values signal "use grid file"

When `zmax`, `depth`, or `rizero` are negative in tr_in.txt, TRIGRS reads spatially variable values from the corresponding grid files. When positive, the scalar value overrides the grid for all cells. This dual behavior is a common source of confusion.

### dk_004: mmax sign controls finite vs infinite depth

When `mmax` is **positive**, the infinite-depth infiltration model is used. When `mmax` is **negative**, the finite-depth model is used (soil resting on an impermeable boundary at depth = zmax). The sign convention is non-obvious and poorly documented.

### dk_005: Unsaturated model requires consistent parameters

The unsaturated infiltration model activates only when `Theta-sat > Theta-res > 0` AND `Alpha > 0`. If Alpha is negative (e.g., -0.5), TRIGRS silently falls back to the saturated model for that zone. To force the saturated model, set `Alpha` to a negative value.

### dk_006: Grid congruence is essential

All input grids (DEM, slope, zones, depth, water table, rainfall) must have identical rows, columns, cell size, and nodata cell locations. Mismatched grids cause crashes or incorrect cell mapping. Always run GridMatch before TRIGRS.

### dk_007: TopoIndex must run before TRIGRS

Even if runoff routing is not used, TopoIndex (or TRIGRS's internal grid reader) must create `TIgrid_size.txt` or `TRgrid_size.txt` containing imax, row, col, nwf. TRIGRS looks for these files in the DEM folder. If they don't exist, TRIGRS reads the DEM directly.

### dk_008: Factor of safety interpretation

FS < 1.0 indicates potentially unstable slopes. FS = 1.0 is the threshold of failure. FS > 1.0 indicates stable conditions. TRIGRS computes the **minimum** FS across all depths at each cell across the simulation. Cells with very low slopes (~0 degrees) produce very high FS values (>> 10).

### dk_009: Cohesion in Pa, not kPa

Soil cohesion must be in **Pascals** (N/m^2). Published values are often in kPa. A cohesion of 3.5 kPa must be entered as 3500 Pa (3.5e+03). Entering 3.5 instead of 3500 produces FS values ~1000x too low.

---

## Tool Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| Rainfall converter | s3 | `tools/convert_rainfall_to_trigrs.py` | ~300 | Convert rainfall time series to TRIGRS intensity grids + tr_in.txt parameters |
| Soil converter | s2 | `tools/convert_soil_to_trigrs.py` | ~280 | Map HWSD/SoilGrids soil classes to TRIGRS zone parameters |
| Execution wrapper | s6 | `tools/run_trigrs.py` | ~350 | Compile source, run TopoIndex and TRIGRS, validate outputs |
| Output parser | s7 | `tools/parse_trigrs_output.py` | ~300 | Extract FS grids, pressure head profiles to CSV + GeoTIFF |
| Init file generator | s5 | `tools/generate_tr_in.py` | ~350 | Assemble tr_in.txt from components with validation |

---

## Calibration Parameters (sensitivity-ordered)

| Priority | Parameter | Symbol | Typical range | Effect on FS |
|----------|-----------|--------|---------------|--------------|
| 1 | Saturated hydraulic conductivity | Ks | 1e-8 to 1e-3 m/s | Controls infiltration rate and timing |
| 2 | Soil cohesion | c | 0 to 50,000 Pa | Direct linear effect on FS |
| 3 | Friction angle | phi | 15 to 45 degrees | tan(phi) in FS denominator |
| 4 | Initial water table depth | dep | 0.5 to 10 m | Sets baseline pore pressure |
| 5 | Hydraulic diffusivity | D0 | 1e-6 to 1e-2 m^2/s | Controls pressure wave speed |
| 6 | Soil depth (zmax) | zmax | 0.5 to 5 m | Limits finite-depth model |
| 7 | Unit weight of soil | uws | 16,000 to 22,000 N/m^3 | Scales driving + resisting forces |
| 8 | Initial infiltration rate | rizero | 0 to Ks m/s | Background steady-state condition |
| 9 | Alpha (Gardner parameter) | alpha | 0.1 to 50 1/m | Controls unsaturated retention |

---

## Quick Start

```bash
# 1. Compile TRIGRS serial binary
cd src/TRIGRS && make trg

# 2. Prepare grid data with GIS
#    Export DEM, slope, zones as ESRI ASCII grids (.asc)
#    Ensure all grids have same extent and cell size

# 3. Run TopoIndex for grid dimensions (optional: runoff routing)
./tpx   # reads tpx_in.txt

# 4. Edit tr_in.txt with soil parameters and file paths
#    CRITICAL: ensure units are m, s, Pa, N/m^3, degrees

# 5. Run TRIGRS
./trg   # reads tr_in.txt from current directory

# 6. Inspect results
#    TRfs_min_*.asc  -> factor of safety grid
#    TrigrsLog.txt   -> run log with mass balance
```

---

## Diagnostic Triplets Summary

18 triplets covering 5 failure domains:
- **unit_conversion** (7 triplets, 39%) -- SILENT errors, highest priority
- **grid_format** (4 triplets, 22%) -- Grid mismatch and nodata issues
- **parameter_logic** (3 triplets, 17%) -- Sign conventions, model selection
- **runtime** (2 triplets, 11%) -- Convergence, memory issues
- **output_interpretation** (2 triplets, 11%) -- Misreading FS, depth values

See `diagnostics/triplets.yaml` for full symptom-diagnosis-remedy entries.

---

## 11. Validated Results

**Status**: body campaign pending. This KI is marked `tutorial_validated` for the USGS tutorial dataset and Srivastava-Yeh column test, but this body does not record a completed field validation campaign.

### Performance Metrics -- judged against `docs/validation_convention.yaml`

The convention file supplies the pass-bands below. Null bands are written as `no cited threshold`; no uncited thresholds are substituted.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band |
|---|---|---|---|---|---|
| `minimum_factor_of_safety` | `tpr_fpr_ratio` | maximize | 1.0 (`raia2014`) | no cited threshold (`raia2014`) | no cited threshold (`raia2014`) |
| `minimum_factor_of_safety` | `rmse_fs` | minimize | 0.15 (`godt2012`) | no cited threshold (`godt2012`) | 0.06 (`godt2012`) |
| `depth_of_minimum_FS` | `pbias` | zero_centered | no cited threshold (no convention citation key) | no cited threshold (no convention citation key) | no cited threshold (no convention citation key) |

No achieved calibration, validation, or full-period metric values are stated in this SKILL body until a sourced body campaign result is added.

### Data Replacement Tracking

| Component | Source | Status | Notes |
|---|---|---|---|
| Forcing | Pipeline | pending field validation | Prepared through the TRIGRS rainfall conversion workflow; field campaign score not recorded in this body. |
| Soil | Pipeline | pending field validation | Prepared through the TRIGRS soil conversion workflow; field campaign score not recorded in this body. |
| DEM and slope | Pipeline / GIS | pending field validation | Grid congruence must be verified before execution. |
| Initial conditions | Pipeline / `tr_in.txt` | pending field validation | Water table depth and initial infiltration must keep TRIGRS units. |
| Outputs | TRIGRS binary/package | tutorial validated | Headline output is `minimum_factor_of_safety`; field campaign score not recorded in this body. |

---

## File Structure

```
ki/
  SKILL.md                              # This file
  knowledge_infrastructure.yaml         # Pipeline and tool schema
  tools/
    convert_rainfall_to_trigrs.py       # Rainfall forcing converter
    convert_soil_to_trigrs.py           # Soil parameter converter
    run_trigrs.py                       # Execution wrapper
    parse_trigrs_output.py              # Output parser
    generate_tr_in.py                   # Initialization file generator
  docs/
    s1_dem_slope_preparation.md         # DEM and slope grid prep
    s2_soil_parameters.md               # Soil property assignment
    s3_rainfall_forcing.md              # Rainfall data conversion
    s4_execution.md                     # Running TRIGRS
    s5_output_analysis.md               # Interpreting results
    s6_calibration_validation.md        # Calibration and validation
  diagnostics/
    triplets.yaml                       # 18 symptom-diagnosis-remedy entries
  workflow/
    (pipeline workflow definitions)
```

---

## References

- Baum, R.L., Savage, W.Z., and Godt, J.W., 2002, TRIGRS--A FORTRAN Program for Transient Rainfall Infiltration and Grid-Based Regional Slope-Stability Analysis: USGS OFR 02-0424.
- Baum, R.L., Savage, W.Z., and Godt, J.W., 2008, TRIGRS version 2.0: USGS OFR 2008-1159, 75 p.
- Baum, R.L., Godt, J.W., and Savage, W.Z., 2010, Estimating the timing and location of shallow rainfall-induced landslides using a model for transient, unsaturated infiltration: JGR Earth Surface, v. 115, F03013.
- Alvioli, M. and Baum, R.L., 2016, Parallelization of the TRIGRS model: Environmental Modelling & Software, v. 81, p. 122-135.
- Iverson, R.M., 2000, Landslide triggering by rain infiltration: Water Resources Research, v. 36, no. 7, p. 1897-1910.
- Srivastava, R. and Yeh, T.-C.J., 1991, Analytical solutions for one-dimensional, transient infiltration: Water Resources Research, v. 27, p. 753-762.
