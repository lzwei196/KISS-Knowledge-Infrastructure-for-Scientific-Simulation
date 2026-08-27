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
| to run the pipeline stages | `tools/` (6 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (6 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (21 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (12 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_connectivity.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_connectivity.py --help` |
| `tools/convert_lsm_to_vlat.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_lsm_to_vlat.py --help` |
| `tools/generate_muskingum_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_muskingum_params.py --help` |
| `tools/generate_namelist.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/generate_namelist.py --help` |
| `tools/parse_rapid_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_rapid_output.py --help` |
| `tools/run_rapid.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_rapid.py --help` |

*6 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# RAPID Knowledge Infrastructure

**Package**: hydrocraft-rapid-routing
**Version**: 1.0.0
**Model**: RAPID (Routing Application for Parallel computatIon of Discharge)
**Domain**: River network routing
**Language**: Fortran 90 + PETSc
**Tools**: 5 | **Skill Documents**: 6 | **Diagnostic Triplets**: 20

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: This model takes runoff from upstream hydrological models (VIC, mHM, etc.) as input.
See `data_ki/ObservedQ/SKILL.md` for observed discharge validation data.

## Output Description

**Source**: `dag.yaml`. The dag is the authoritative source for observable
outputs; if this section and `dag.yaml` disagree, `dag.yaml` wins.

**Headline output**: `Qout` — Discharge at the outlet of each river reach per output time step (primary output). (`m3/s`)

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| Qout | 1 | m3/s | Discharge at the outlet of each river reach per output time step (primary output). |
| V | not restated in extracted facts | not restated in extracted facts | other dag output |
| Qfinal | not restated in extracted facts | not restated in extracted facts | other dag output |


## Overview

RAPID computes discharge and water volume across entire river networks using the
Muskingum routing method with PETSc for parallel linear algebra. It takes lateral
inflow volumes (typically from a land-surface model such as VIC, Noah, or GLDAS)
and routes them through a river connectivity network to produce reach-level
discharge (m³/s) and storage volume (m³) time series.

Key characteristics:
- **Muskingum method**: Linear channel routing with parameters k (travel time, seconds)
  and x (attenuation weighting, dimensionless 0–0.5)
- **PETSc solver**: Sparse matrix assembly and Krylov subspace methods for parallel routing
- **TAO optimization**: Automatic calibration of k and x against observed gage data
- **Kalman filter**: Data assimilation mode for correcting runoff estimates
- **NetCDF I/O**: All time-varying inputs/outputs use CF-compliant NetCDF
- **CSV parameters**: Static connectivity and parameters use space/tab-delimited CSV

### What Makes RAPID Different

| Feature | RAPID | Other routing models |
|---------|-------|---------------------|
| Parallelism | PETSc distributed matrices | Typically serial |
| Routing | Muskingum (matrix form) | Muskingum-Cunge, kinematic wave |
| Calibration | Built-in TAO optimizer | External calibration tools |
| Data assimilation | Kalman filter on runoff | Typically post-processing |
| Scale | Continental to global | Usually basin-scale |

---

## Installation

### Docker (Recommended)

```bash
cd /path/to/rapid
docker build -t chdavid/rapid:latest .
docker run --rm -it chdavid/rapid
# Inside container: cd src/ && ./rapid --help
```

### Native Build (Debian/Ubuntu)

```bash
# 1. Install system packages
sudo apt-get install -y $(grep -v -E '(^#|^$)' requirements.apt)

# 2. Install PETSc 3.13.6
export INSTALLZ_DIR=$HOME/installz
mkdir -p $INSTALLZ_DIR
./rapid_install_prereqs.sh --installz=$INSTALLZ_DIR

# 3. Set environment
source ./rapid_specify_varpath.sh $INSTALLZ_DIR

# 4. Build
cd src/ && make rapid

# 5. Build test utilities
cd ../tst/ && gfortran -o tst_run_comp tst_run_comp.f90 $(nf-config --fflags --flibs)
```

### Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| gfortran | ≥7 | Fortran compiler |
| PETSc | 3.13.6 | Parallel linear algebra |
| MPICH | (bundled with PETSc) | MPI communication |
| NetCDF-Fortran | ≥4.5 | NetCDF I/O |
| BLAS/LAPACK | (bundled with PETSc) | Dense linear algebra |
| Python 3 | ≥3.6 | PETSc build, driver scripts |

### Environment Variables

```bash
export PETSC_DIR=$INSTALLZ_DIR/petsc-3.13.6
export PETSC_ARCH=linux-gcc-c
export NETCDF_LIB='-L /usr/lib -lnetcdff'
export NETCDF_INCLUDE='-I /usr/include'
export PATH=$PATH:$PETSC_DIR/$PETSC_ARCH/bin
```

---

## Pipeline

The RAPID workflow consists of 9 stages:

```
s0_acquire ──► s1_connectivity ──► s2_lateral_inflow ──► s3_parameters ──┐
                                                                         │
s4_namelist ◄──────────────────────────────────────────────────────────────┘
     │
     ▼
s5_execution ──► s6_output_analysis ──► s7_optimization ──► s8_coupling
```

| # | Stage | Description | Parallel? |
|---|-------|-------------|-----------|
| 0 | Acquire | Obtain RAPID source and build binary | — |
| 1 | Connectivity | Build rapid_connect, riv_bas_id CSV files from river network | — |
| 2 | Lateral Inflow | Convert LSM runoff to Vlat NetCDF (m³ per routing period) | ∥ with s3 |
| 3 | Parameters | Generate Muskingum k (seconds) and x (dimensionless) CSV files | ∥ with s2 |
| 4 | Namelist | Assemble Fortran namelist with all paths and temporal settings | after s1–s3 |
| 5 | Execution | Run `./rapid -nl <namelist>` with MPI | after s4 |
| 6 | Output Analysis | Parse Qout/V NetCDF, compute metrics, plot hydrographs | after s5 |
| 7 | Optimization | Calibrate k and x using TAO against observed discharge | optional |
| 8 | Coupling | Feed RAPID discharge to downstream models (lakes, floodplains) | optional |

---

## Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| convert_lsm_to_vlat | s2 | `tools/convert_lsm_to_vlat.py` | ~220 | Convert LSM runoff to RAPID Vlat NetCDF |
| generate_muskingum_params | s3 | `tools/generate_muskingum_params.py` | ~200 | Generate k and x CSV from reach properties |
| generate_namelist | s4 | `tools/generate_namelist.py` | ~250 | Assemble RAPID Fortran namelist |
| run_rapid | s5 | `tools/run_rapid.py` | ~180 | Execute RAPID with preflight checks |
| parse_rapid_output | s6 | `tools/parse_rapid_output.py` | ~240 | Extract discharge/volume, compute metrics |

---

## Critical Domain Knowledge

### 1. Vlat Units: Volume, NOT Rate (SILENT ERROR)

RAPID expects lateral inflow as **volume** (m³) accumulated over the routing period
`ZS_TauR`, not as a flow rate (m³/s). The conversion from rate to volume happens
inside RAPID: `Qlat = Vlat / TauR`. If you feed m³/s directly as Vlat, discharge
will be divided by TauR again, producing values ~10,800× too small.

**Trap**: LSM outputs are often in kg/m²/s (= mm/s for water). Converting to m³
requires: `Vlat = runoff_mm_s × area_m2 × TauR_s / 1000`.

### 2. Muskingum k Is in Seconds, Not Hours

The `k_file` CSV contains travel time per reach in **seconds**. A common error is
providing k in hours (e.g., 2.5 hours → must be 9000 seconds). If k is too small,
the Muskingum C1/C2/C3 coefficients become unstable (C1 or C3 < 0).

**Stability criterion**: `k × x ≤ dt/2 ≤ k × (1-x)` where dt = ZS_dtR in seconds.

### 3. Connectivity File Format Is Strict

The `rapid_connect_file` must have exactly this format per line:
```
reach_id  downstream_id  num_upstream  upstream_id_1  upstream_id_2 ...
```
- `downstream_id = 0` for outlet reaches (no downstream)
- `num_upstream = 0` for headwater reaches (no upstream IDs follow)
- Reach IDs must match those in `riv_bas_id_file`
- Maximum upstream count must match `IS_max_up` in namelist

### 4. Time Parameters Are All in Seconds

| Parameter | Meaning | Typical Value | Units |
|-----------|---------|---------------|-------|
| ZS_TauM | Total simulation duration | 2592000 (30 days) | seconds |
| ZS_dtM | Main output time step | 86400 (1 day) | seconds |
| ZS_TauR | Routing procedure period | 10800 (3 hours) | seconds |
| ZS_dtR | Routing sub-step | 900 (15 minutes) | seconds |

**Consistency checks**:
- `ZS_TauM` must be divisible by `ZS_dtM`
- `ZS_TauR` must be divisible by `ZS_dtR`
- `ZS_TauM` must be divisible by `ZS_TauR`
- Number of Vlat time steps in NetCDF = `ZS_TauM / ZS_TauR`

### 5. Reach ID Ordering Matters

The order of reaches in `riv_bas_id_file` determines the row ordering in all
PETSc vectors. The Vlat NetCDF variable must have reaches in the same order
as the connectivity file. Mismatched ordering produces silently wrong results.

### 6. NetCDF Variable Names Are Fixed

| File | Variable | Dimensions | Units |
|------|----------|------------|-------|
| Vlat input | `Vlat` | (time, rivid) | m³ |
| Qout output | `Qout` | (time, rivid) | m³/s |
| V output | `V` | (time, rivid) | m³ |
| Qinit/Qfinal | `Qout` | (time=1, rivid) | m³/s |
| Qobs | `Qobs` | (time, rivid) | m³/s |

### 7. PETSc Processor Count Affects Results Slightly

Due to floating-point summation order, running with different numbers of MPI
processes can produce slightly different results (< 1e-10 relative difference).
This is normal and not a bug.

### 8. Optimization Mode Requires Observation Data

Running IS_opt_run=2 (optimization) requires:
- `Qobs_file`: NetCDF with observed discharge at gage locations
- `obs_tot_id_file`, `obs_use_id_file`: CSV lists of gage reach IDs
- `ZS_TauO`, `ZS_dtO`: Optimization time window parameters

### 9. Initial Conditions Default to Zero

If `BS_opt_Qinit = .false.`, all reaches start with zero flow. For large
basins this causes a spinup period of days to weeks. Best practice: run a
1-year warmup, save Qfinal, use as Qinit for production runs.

---

## Unit Trap Table

| Variable | Expected Unit | Common Wrong Unit | Scale Factor | Consequence |
|----------|--------------|-------------------|--------------|-------------|
| Vlat | m³ (volume) | m³/s (rate) | × TauR | Discharge ~10800× too small |
| k | seconds | hours | × 3600 | Muskingum instability, NaN |
| x | dimensionless (0–0.5) | percentage (0–50) | ÷ 100 | Numerical explosion |
| ZS_TauM | seconds | days | × 86400 | Wrong simulation length |
| ZS_dtR | seconds | minutes | × 60 | Courant violation |
| Rain (LSM) | kg/m²/s = mm/s | mm/day | ÷ 86400 | 86400× overestimate in Vlat |
| Reach area | m² | km² | × 1e6 | Vlat wrong by 1e6 |

---

## Unit Conversion Table

This table records the unit conversions and unit traps already stated in this
KI. Exact I/O shapes and units live in `docs/format_spec.yaml`; observable
outputs are governed by `dag.yaml`.

| Variable | Source unit (verified) | Model unit | Factor | Type |
|----------|------------------------|------------|--------|------|
| Vlat | kg/m²/s (= mm/s for water) over reach area and routing period | m³ accumulated over `ZS_TauR` | area_m2 × TauR_s / 1000 | multiplicative |
| Vlat | m³/s | m³ accumulated over `ZS_TauR` | × TauR | multiplicative |
| k | hours | seconds | × 3600 | multiplicative |
| x | percentage (0–50) | dimensionless (0–0.5) | ÷ 100 | multiplicative |
| ZS_TauM | days | seconds | × 86400 | multiplicative |
| ZS_dtR | minutes | seconds | × 60 | multiplicative |
| Rain (LSM) | mm/day | kg/m²/s = mm/s | ÷ 86400 | multiplicative |
| Reach area | km² | m² | × 1e6 | multiplicative |
| Qout | model output | m3/s | no conversion | output unit from dag.yaml |

---

## Validated Results

### Headline Output and Convention Bars

**Source**: `dag.yaml` for the rank-1 output and
`docs/validation_convention.yaml` for metric directions, bands, and citation
keys. Bands held as null in the convention are stated as `no cited threshold`.

| dag variable | Metric | Direction | Very good | Good | Satisfactory | Citation key |
|--------------|--------|-----------|-----------|------|--------------|--------------|
| Qout | nse | maximize | 0.75 (me2015) | 0.65 (me2015) | 0.5 (me2015) | me2015 |
| Qout | pbias | zero_centered | 10 (me2015) | 15 (me2015) | 25 (me2015) | me2015 |
| Qout | pbias | zero_centered | no cited threshold | no cited threshold | no cited threshold | no citation |
| Qout | nse | maximize | 0.75 (me2015) | 0.65 (me2015) | 0.5 (me2015) | me2015 |
| Qout | pbias | zero_centered | 10 (me2015) | 15 (me2015) | 25 (me2015) | me2015 |

### Published Reproduction Runs

The older validation summary below is retained as existing KI content. Grade
new runs against the convention bars above, using `Qout` as the rank-1 output.

## Validation Results

### San Antonio–Guadalupe Basin (David et al., 2011 JHM)

Published test case from the JHM 2011 paper. GLDAS-VIC forcing, 3-hourly
routing, 15-minute sub-steps, 5,175 river reaches.

| Metric | Published | Reproduced |
|--------|-----------|------------|
| NSE (monthly) | 0.52–0.89 | 0.52–0.89 |
| Correlation | 0.72–0.96 | 0.72–0.96 |
| Bias (%) | -20 to +15 | -20 to +15 |

### MERIT-Hydro Global Basins (David et al., 2015 WRR)

Continental-scale routing over NHDPlus, ~2.6M reaches.

---

## Calibration Parameters

| Parameter | Namelist | Range | Default | Sensitivity |
|-----------|----------|-------|---------|-------------|
| k (per reach) | k_file CSV | 900–360000 s | — | HIGH |
| x (per reach) | x_file CSV | 0.0–0.5 | 0.1–0.3 | MEDIUM |
| ZS_dtR | namelist | 300–3600 s | 900 | LOW (stability) |
| kfac (multiplier) | kfac_file | 0.1–10.0 | 1.0 | HIGH |
| xfac (multiplier) | xfac_file | 0.1–5.0 | 1.0 | MEDIUM |

Optimization uses TAO (mode IS_opt_run=2) to minimize sum of squared errors
between simulated and observed discharge at gage locations.

---

## Coupling Points

| Upstream Model | Variable | Direction | Format |
|----------------|----------|-----------|--------|
| VIC / Noah / GLDAS | Surface + subsurface runoff | → RAPID Vlat | NetCDF m³ |
| MERIT-Hydro / NHDPlus | River connectivity | → RAPID CSV | CSV |
| Observed gages | Discharge | → RAPID Qobs | NetCDF m³/s |
| RAPID Qout | Discharge | → Lake/reservoir model | NetCDF m³/s |
| RAPID Qout | Discharge | → CaMa-Flood | NetCDF m³/s |
| RAPID V | Storage volume | → Water management | NetCDF m³ |

---

## Quick Start

```bash
# Build with Docker
docker build -t rapid:latest .
docker run --rm -it -v $(pwd)/data:/data rapid:latest

# Run a simulation
cd /data
mpiexec -np 4 /path/to/rapid -nl rapid_namelist

# Check output
ncdump -h Qout_file.nc
python3 -c "import netCDF4; d=netCDF4.Dataset('Qout_file.nc'); print(d['Qout'][:].shape)"
```

---

## Diagnostic Triplets Summary

| ID | Stage | Symptom | Severity |
|----|-------|---------|----------|
| dt_001 | s2 | Discharge near zero everywhere | silent |
| dt_002 | s3 | NaN in Qout after first time step | fatal |
| dt_003 | s3 | Negative discharge values | degraded |
| dt_004 | s1 | Segfault during matrix assembly | fatal |
| dt_005 | s4 | "namelist read error" at startup | fatal |
| dt_006 | s2 | Discharge 86400× too large | silent |
| dt_007 | s1 | Reaches missing from output | silent |
| dt_008 | s5 | "KSP diverged" error | fatal |
| dt_009 | s4 | Time step mismatch warning | degraded |
| dt_010 | s2 | Flat hydrograph, no peaks | silent |

---

## File Structure

```
ki/
├── SKILL.md                          # This file
├── tools/
│   ├── convert_lsm_to_vlat.py       # LSM runoff → RAPID Vlat NetCDF
│   ├── generate_muskingum_params.py  # Reach properties → k, x CSV
│   ├── generate_namelist.py          # Assemble Fortran namelist
│   ├── run_rapid.py                  # Execute RAPID binary
│   └── parse_rapid_output.py         # Parse Qout/V, compute metrics
├── docs/
│   ├── s1_connectivity.md            # River network connectivity
│   ├── s2_lateral_inflow.md          # LSM to Vlat conversion
│   ├── s3_parameters.md              # Muskingum k and x
│   ├── s4_namelist.md                # Namelist assembly
│   ├── s5_execution.md               # Running RAPID
│   └── s6_output_analysis.md         # Output parsing and metrics
└── diagnostics/
    └── triplets.yaml                 # 20 symptom→diagnosis→remedy entries
```
