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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (8 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (19 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/build_roms_grid.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/build_roms_grid.py --help` |
| `tools/convert_forcing.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing.py --help` |
| `tools/parse_roms_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_roms_output.py --help` |
| `tools/run_roms.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_roms.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# hydrocraft-roms-ocean v1.0.0

**Target Model:** ROMS v4.1 (Regional Ocean Modeling System)
**Domain:** Ocean hydrodynamics, coastal/estuarine modeling
**Developers:** Rutgers University — H. Arango, A. Shchepetkin, J. Warner
**License:** MIT/X style
**Repository:** https://github.com/myroms/roms

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## 1. Overview

ROMS (Regional Ocean Modeling System) solves the free-surface, hydrostatic,
primitive equations on a stretched terrain-following (sigma/s-coordinate)
vertical grid using finite-volume discretization on an Arakawa C-grid.
It supports nested grids, multiple vertical mixing closures (KPP, GLS,
Mellor-Yamada 2.5), biological modules (Fennel, NEMURO, EcoSim), sediment
transport, sea-ice dynamics, and wave-current interaction (WEC).

ROMS reads all forcing and initial/boundary data from **NetCDF** files.
Configuration is via a plain-text standard-input file (`roms.in`) plus
C-preprocessor (CPP) header files that enable/disable physics options at
compile time. Outputs are NetCDF history, average, diagnostic, station,
and restart files.

### Key capabilities

| Feature | Details |
|---------|---------|
| Horizontal grid | Orthogonal curvilinear, Arakawa C-grid |
| Vertical grid | Stretched terrain-following S-coordinates (Vtransform 1 or 2) |
| Time stepping | Split-explicit: fast barotropic (2D) + slow baroclinic (3D) |
| Mixing closures | KPP (LMD), GLS (k-ε, k-ω, gen), MY2.5 |
| Nesting | 1-way and 2-way, refinement and composition |
| Data assimilation | 4D-Var (IS4DVAR, I4DVAR, R4DVAR), adjoint, tangent linear |
| Parallelism | MPI domain decomposition (NtileI × NtileJ) |
| Biology | Fennel, NEMURO, EcoSim, RED_TIDE, BIO_UMAINE |
| Sediment | BBL closures (SSW, MB, SG), bed load, suspended load |
| Waves | WEC (Stokes drift, radiation stress, wave breaking) |
| Ice | Sea-ice dynamics and thermodynamics |

---

## 2. Installation

### 2.1 Dependencies

| Dependency | Required | Purpose |
|------------|----------|---------|
| NetCDF-Fortran | **Yes** | All I/O |
| NetCDF-C | **Yes** | Underlying C library |
| MPI (OpenMPI/MPICH) | Recommended | Parallel execution |
| CMake ≥ 3.13 | **Yes** (CMake build) | Build system |
| Fortran compiler | **Yes** | gfortran ≥ 9 or Intel ifort/ifx |
| ESMF | Optional | Earth System Model coupling |
| ARPACK/PARPACK | Optional | Eigenvalue problems (4D-Var) |

### 2.2 Build (CMake)

```bash
cd /path/to/roms/source/repo
export MY_CPP_FLAGS="-DUPWELLING"
export MY_HEADER_DIR="ROMS/Include"
mkdir build && cd build
cmake .. \
  -DAPP=UPWELLING \
  -DROMS_APP_HEADER=upwelling.h \
  -DCMAKE_Fortran_COMPILER=gfortran
make -j$(nproc)
```

### 2.3 Build (Traditional Makefile)

```bash
cd /path/to/roms/source/repo
# Edit makefile: set ROMS_APPLICATION, MY_HEADER_DIR, MY_ANALYTICAL_DIR
make
```

### 2.4 Verify

```bash
./romsM < ROMS/External/roms_upwelling.in   # MPI version
# or
./romsS < ROMS/External/roms_upwelling.in   # serial version
```

---

## 3. Pipeline Stages

| # | Stage | Description | Key Tool | Depends On |
|---|-------|-------------|----------|------------|
| S0 | Domain & Grid | Define domain extent, resolution, bathymetry | `build_roms_grid.py` | — |
| S1 | CPP Configuration | Select physics options via header file | Manual / template | S0 |
| S2 | Atmospheric Forcing | Convert met data → ROMS NetCDF forcing | `convert_forcing.py` | S0 |
| S3 | Initial Conditions | Create initial T/S/velocity/zeta fields | `convert_forcing.py` | S0 |
| S4 | Boundary Conditions | Generate open-boundary NetCDF files | `convert_forcing.py` | S0 |
| S5 | Tidal Forcing | Extract tidal constituents for domain | External (OTPS) | S0 |
| S6 | Build Binary | Compile ROMS with selected CPP options | CMake / Make | S1 |
| S7 | Execute Model | Run ROMS binary with `roms.in` | `run_roms.py` | S0–S6 |
| S8 | Post-process | Parse NetCDF output, extract time series | `parse_roms_output.py` | S7 |
| S9 | Validate | Compare to observations, compute metrics | `parse_roms_output.py` | S8 |
| S10 | Calibrate | Tune mixing, drag coefficients | Manual iteration | S9 |

---

## 4. Unit Trap Table

These are the most dangerous unit/format errors when preparing ROMS inputs.
Errors marked **SILENT** produce no runtime error but corrupt results.

| # | Variable | ROMS expects | Common source | Trap | Severity |
|---|----------|-------------|---------------|------|----------|
| U1 | Wind stress (sustr/svstr) | N/m² (Pa) | m/s (speed) | Must convert speed→stress via bulk formula or supply stress directly | **SILENT** |
| U2 | Shortwave radiation (srflx) | W/m² (positive downward) | Upward positive | Sign flip → ocean loses heat instead of gaining | **SILENT** |
| U3 | Longwave radiation (lrflx) | W/m² (net, positive = warming) | Downwelling only | Missing upwelling component → unrealistic heating | **SILENT** |
| U4 | Precipitation (rain) | kg/m²/s | mm/day or mm/hr | mm/day → kg/m²/s: ÷ 86400 (1 mm = 1 kg/m²) | **SILENT** |
| U5 | Specific humidity (Qair) | kg/kg | % relative humidity | Must convert RH → specific humidity using Tair, Pair | **SILENT** |
| U6 | Air pressure (Pair) | mb (hPa) | Pa | Pa → mb: ÷ 100 | **SILENT** |
| U7 | Bathymetry (h) | meters (positive down) | Negative depths | Negative h → model crash or land everywhere | **FATAL** |
| U8 | Temperature (temp) | °C | Kelvin | K → °C: subtract 273.15 | **SILENT** |
| U9 | Salinity (salt) | PSU (g/kg) | ‰ or mg/L | Already equivalent if PSU; mg/L needs conversion | **SILENT** |
| U10 | Time (ocean_time) | seconds since ref date | days or hours | Must match `time_ref` in roms.in | **FATAL** |
| U11 | Grid metrics (pm/pn) | 1/meters | meters | Inverted → CFL blow-up or extreme diffusion | **FATAL** |
| U12 | Coriolis (f) | 1/s | degrees | Must compute f = 2Ω sin(lat) | **SILENT** |
| U13 | THETA_S/THETA_B range | 0 < θs ≤ 10, 0 ≤ θb ≤ 4 | Out of range | Extreme stretching → thin layers, CFL violation | **FATAL** |
| U14 | dt (baroclinic) | seconds | minutes or hours | Too large dt → numerical instability | **FATAL** |
| U15 | NDTFAST ratio | dt/dtfast ≈ 20–60 | Too small | Poor barotropic–baroclinic coupling | **DEGRADED** |

---

## 5. Critical Domain Knowledge

### 5.1 S-coordinate vertical grid
ROMS uses terrain-following coordinates. The stretching function is controlled
by `Vtransform` (1 or 2), `Vstretching` (1–5), `THETA_S` (surface control),
`THETA_B` (bottom control), and `TCLINE` (critical depth). A common mistake
is using Vtransform=1 parameters with Vtransform=2 — they have different
formulations and parameter ranges.

### 5.2 Arakawa C-grid staggering
Variables live on different grid points:
- **RHO-points:** tracers (T, S), free-surface (zeta), density
- **U-points:** XI-direction velocity (u, ubar)
- **V-points:** ETA-direction velocity (v, vbar)
- **PSI-points:** vorticity, streamfunction

Forcing fields must be on the correct staggered grid. Wind stress components
`sustr` and `svstr` go on U and V points respectively. Scalars (Tair, Pair,
rain, radiation) go on RHO points.

### 5.3 Boundary condition specification
Lateral boundary conditions are set per-variable per-edge in `roms.in`:
```
LBC(isFsur) ==   Per   Clo   Per   Clo     ! free-surface
LBC(isUbar) ==   Per   Clo   Per   Clo     ! 2D U-momentum
```
Order is always: **West South East North**. Options include:
- `Per` (periodic), `Clo` (closed wall), `Gra` (gradient)
- `Rad` (radiation), `RadNud` (radiation + nudging)
- `Cla` (Clamped to boundary data), `Fla` (Flather)

### 5.4 Time reference and calendar
ROMS tracks time as seconds since a reference date set by `TIME_REF` in
`roms.in` (format: YYYYMMDD.dd). All NetCDF time variables must be in
**seconds** relative to this same epoch. Mixing Julian days, modified Julian
days, or different reference dates is a common silent error.

### 5.5 Wet/dry masking
When `WET_DRY` is enabled, cells can dynamically flood and dry. The critical
depth `DCRIT` controls the minimum water depth. Setting it too small causes
instabilities; too large prevents proper inundation.

### 5.6 NetCDF variable metadata
ROMS checks `varinfo.yaml` (or legacy `varinfo.dat`) to map internal variable
names to NetCDF variable names. If your forcing file uses non-standard names,
you must either rename them or edit `varinfo.yaml`.

### 5.7 Bulk flux computation
When `BULK_FLUXES` is defined, ROMS computes air-sea fluxes internally from
atmospheric state variables (Tair, Pair, Qair, rain, Uwind, Vwind, lwrad,
swrad). Do NOT also supply precomputed fluxes — this will double-count.

### 5.8 CFL stability criterion
The barotropic time step must satisfy:
```
dtfast < dx / sqrt(g * hmax)
```
where `dx` is minimum grid spacing and `hmax` is maximum depth. The
baroclinic step `dt` should be NDTFAST × dtfast. Typical NDTFAST = 20–60.

### 5.9 Nudging coefficients
When using `RadNud` boundary conditions, nudging time scales (`Tnudg` in
`roms.in`) are in **days**. Setting them too small (strong nudging) can cause
boundary artifacts; too large (weak nudging) lets boundary data drift.

---

## 6. Output Description

**Source:** `dag.yaml`. The dag is the model identity for observable outputs;
if this section ever disagrees with `dag.yaml`, the dag wins.

**Headline output** (`validation_rank: 1` in `dag.yaml`):

> `zeta` — Free-surface elevation (sea surface height); barotropic prognostic state (m)

| Output variable (dag `var`) | Rank / role | Unit | Description |
|-----------------------------|-------------|------|-------------|
| `zeta` | 1 | m | Free-surface elevation (sea surface height); barotropic prognostic state |
| `temp` | other dag output | see `dag.yaml` | listed in `dag.yaml` outputs |
| `salt` | other dag output | see `dag.yaml` | listed in `dag.yaml` outputs |
| `u` | other dag output | see `dag.yaml` | listed in `dag.yaml` outputs |
| `v` | other dag output | see `dag.yaml` | listed in `dag.yaml` outputs |
| `ubar, vbar` | other dag output | see `dag.yaml` | listed in `dag.yaml` outputs |
| `rho` | other dag output | see `dag.yaml` | listed in `dag.yaml` outputs |

---

## 7. Validation Benchmark

### Idealized Upwelling Test Case
- **Domain:** Periodic channel, 41 × 80 × 16 grid
- **Forcing:** Along-shore wind stress (0.1 N/m²)
- **Expected:** Coastal upwelling on right coast (Northern Hemisphere),
  surface Ekman transport offshore, cold water upwelling at coast
- **Verification:** Temperature cross-section shows tilted isotherms,
  upwelling velocity O(10⁻⁴ m/s), surface cooling at coast

### Realistic validation approach
For realistic domains, compare against:
- Tide gauge sea level / free surface: grade `zeta` against the cited
  convention bars in Section 11 (`skill_index`, `rmse`, and `r`).
- CTD/ARGO temperature profiles and satellite SST: grade `temp` against the
  cited `rmse` convention bar in Section 11.
- Current meter validation uses ROMS velocity outputs (`u`, `v`, `ubar`,
  `vbar`); no cited velocity threshold is restated here from the supplied
  convention facts.

---

## 8. Unit Table and Unit Conversion Table

**Source:** `dag.yaml` for output units, plus the ROMS input/forcing
requirements documented elsewhere in this file. Exact machine-readable I/O
shapes live in `docs/format_spec.yaml`.

### 8.1 Output unit table

| Variable | Unit | Source |
|----------|------|--------|
| `zeta` | m | `dag.yaml` |
| `temp` | see `dag.yaml` | `dag.yaml` output list |
| `salt` | see `dag.yaml` | `dag.yaml` output list |
| `u` | see `dag.yaml` | `dag.yaml` output list |
| `v` | see `dag.yaml` | `dag.yaml` output list |
| `ubar, vbar` | see `dag.yaml` | `dag.yaml` output list |
| `rho` | see `dag.yaml` | `dag.yaml` output list |

### 8.2 Critical input unit conversions

| Variable | Source unit | Model unit | Conversion / check |
|----------|-------------|------------|--------------------|
| Wind stress (`sustr`, `svstr`) | wind speed (`m/s`) or stress | N/m² (Pa) | Convert speed to stress via a bulk formula, or supply stress directly |
| Shortwave radiation (`srflx`) | may be upward-positive | W/m², positive downward | Flip sign if the source is upward-positive |
| Longwave radiation (`lrflx`) | downwelling-only or net | W/m², net warming sign | Include the upwelling component if ROMS expects net flux |
| Precipitation (`rain`) | mm/day or mm/hr | kg/m²/s | Convert mm/day by dividing by 86400; 1 mm water depth = 1 kg/m² |
| Specific humidity (`Qair`) | relative humidity (%) | kg/kg | Convert RH to specific humidity from air temperature and pressure |
| Air pressure (`Pair`) | Pa | mb (hPa) | Divide Pa by 100 |
| Bathymetry (`h`) | negative depths in some sources | meters, positive down | Store positive depth values |
| Temperature (`temp`, `Tair`) | K | °C | Subtract 273.15 |
| Salinity (`salt`) | PSU, ‰, or mg/L | PSU (g/kg) | PSU/‰ are equivalent for practical use; mg/L requires conversion |
| Time (`ocean_time`) | days or hours in some sources | seconds since `TIME_REF` | Convert to seconds and match `TIME_REF` in `roms.in` |
| Grid metrics (`pm`, `pn`) | meters | 1/meters | Invert grid spacing |
| Coriolis (`f`) | latitude degrees | 1/s | Compute `f = 2Ω sin(lat)` |

---

## 11. Validated Results

**Source:** `docs/validation_convention.yaml`. These are convention bars, not
achieved run metrics. Grade actual calibration/validation outputs against these
cited bars after `tools/parse_roms_output.py` computes the metric values.

### Performance metrics -- judged against the field's bar, not intuition

| Variable | Metric | Direction | Very good | Good | Satisfactory |
|----------|--------|-----------|-----------|------|--------------|
| `zeta` | `skill_index` | maximize | ≥ 0.95 (haidvogel2008; warner2005) | ≥ 0.92 (haidvogel2008; warner2005) | ≥ 0.85 (haidvogel2008; warner2005) |
| `zeta` | `rmse` | minimize | ≤ 0.076 (kerry2016; nolan2020) | ≤ 0.15 (kerry2016; nolan2020) | ≤ 0.17 (kerry2016; nolan2020) |
| `zeta` | `rmse` | minimize | ≤ 0.04 (haidvogel2008; kerry2016) | ≤ 0.076 (haidvogel2008; kerry2016) | ≤ 0.076 (haidvogel2008; kerry2016) |
| `zeta` | `r` | maximize | no cited threshold (haidvogel2008) | no cited threshold (haidvogel2008) | ≥ 0.8 (haidvogel2008) |
| `temp` | `rmse` | minimize | no cited threshold (nolan2020; kerry2016) | ≤ 0.8 (nolan2020; kerry2016) | ≤ 1.0 (nolan2020; kerry2016) |

No achieved calibration, validation, or full-period metric values are restated
here from the supplied KI facts. When achieved values are produced, record the
value and verdict without changing the convention bars above.

---

## 12. Calibration Parameters

| Parameter | Range | Sensitivity | Description |
|-----------|-------|-------------|-------------|
| `VISC2` | 1–100 m²/s | High | Horizontal viscosity |
| `TNU2` | 0–50 m²/s | High | Horizontal tracer diffusivity |
| `AKT_BAK` | 1e-6–1e-4 m²/s | Medium | Background tracer vertical diffusivity |
| `AKV_BAK` | 1e-6–1e-4 m²/s | Medium | Background momentum vertical diffusivity |
| `THETA_S` | 0.1–10 | High | Surface stretching parameter |
| `THETA_B` | 0–4 | Medium | Bottom stretching parameter |
| `TCLINE` | 5–200 m | Medium | Critical depth for stretching |
| `Zob` | 0.001–0.05 m | High | Bottom roughness length |
| `RDRG2` | 0–0.01 | Medium | Quadratic bottom drag coefficient |
| `Tnudg` | 1–360 days | Medium | Boundary nudging time scale |

---

## 8. Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| Grid builder | `tools/build_roms_grid.py` | Create ROMS grid NetCDF from bathymetry + extent |
| Forcing converter | `tools/convert_forcing.py` | Convert global met/ocean data → ROMS NetCDF forcing |
| Execution wrapper | `tools/run_roms.py` | Compile (optional) and run ROMS binary |
| Output parser | `tools/parse_roms_output.py` | Extract time series and profiles from NetCDF output |

---

## 9. Input File Format Reference

### 9.1 roms.in (Standard Input)
Plain text, keyword-value pairs. Lines starting with `!` are comments.
Multi-value parameters use `==` separator. Example:
```
TITLE = My Simulation
NTIMES == 8640
DT == 300.0d0
NDTFAST == 30
```

### 9.2 Grid file (NetCDF)
Required variables:
- `xl`, `el` — domain lengths (m)
- `spherical` — 0=Cartesian, 1=spherical
- `h(eta_rho, xi_rho)` — bathymetry (m, positive)
- `pm(eta_rho, xi_rho)` — 1/dx (1/m)
- `pn(eta_rho, xi_rho)` — 1/dy (1/m)
- `lon_rho`, `lat_rho` — coordinates (degrees)
- `mask_rho` — land/sea mask (0=land, 1=sea)
- `angle` — grid rotation angle (radians)

### 9.3 Forcing file (NetCDF)
Time-varying atmospheric fields on RHO-grid:
- `Uwind(time, eta_rho, xi_rho)` — 10m wind E-component (m/s)
- `Vwind(time, eta_rho, xi_rho)` — 10m wind N-component (m/s)
- `Tair(time, eta_rho, xi_rho)` — air temperature (°C)
- `Pair(time, eta_rho, xi_rho)` — surface pressure (mb)
- `Qair(time, eta_rho, xi_rho)` — specific humidity (kg/kg)
- `rain(time, eta_rho, xi_rho)` — precipitation (kg/m²/s)
- `swrad(time, eta_rho, xi_rho)` — shortwave radiation (W/m²)
- `lwrad(time, eta_rho, xi_rho)` — longwave radiation (W/m²)

### 9.4 Initial conditions file (NetCDF)
- `ocean_time` — initialization time (seconds)
- `zeta(time, eta_rho, xi_rho)` — free-surface (m)
- `ubar(time, eta_u, xi_u)` — 2D U-velocity (m/s)
- `vbar(time, eta_v, xi_v)` — 2D V-velocity (m/s)
- `u(time, s_rho, eta_u, xi_u)` — 3D U-velocity (m/s)
- `v(time, s_rho, eta_v, xi_v)` — 3D V-velocity (m/s)
- `temp(time, s_rho, eta_rho, xi_rho)` — temperature (°C)
- `salt(time, s_rho, eta_rho, xi_rho)` — salinity (PSU)

### 9.5 Boundary conditions file (NetCDF)
Same variables as initial conditions but with `_west`, `_east`, `_south`,
`_north` suffixes and corresponding reduced dimensions.

### 9.6 Output files (NetCDF)
- **History** (`*_his.nc`): snapshots at NHIS intervals
- **Averages** (`*_avg.nc`): time-averaged at NAVG intervals
- **Diagnostics** (`*_dia.nc`): budget terms
- **Stations** (`*_sta.nc`): point extractions
- **Restart** (`*_rst.nc`): full state for continuation

---

## 10. Configuration via CPP Flags

Physics options are selected at compile time via CPP preprocessor flags in
the application header file (e.g., `upwelling.h`):

```fortran
#define UV_ADV          /* advection of momentum */
#define UV_COR          /* Coriolis force */
#define UV_QDRAG        /* quadratic bottom drag */
#define DJ_GRADPS       /* pressure gradient (Shchepetkin & McWilliams) */
#define SALINITY        /* include salinity as tracer */
#define SOLVE3D         /* 3D baroclinic equations */
#define SPLINES_VVISC   /* spline vertical viscosity */
#define SPLINES_VDIFF   /* spline vertical diffusion */
#define BULK_FLUXES     /* atmospheric bulk flux formulas */
#define ANA_SMFLUX      /* analytical surface momentum flux */
#define ANA_STFLUX      /* analytical surface tracer flux */
#define ANA_BTFLUX      /* analytical bottom tracer flux */
#define ANA_SSFLUX      /* analytical surface salinity flux */
#define MIX_S_UV        /* mixing along S-surfaces for momentum */
#define MIX_S_TS        /* mixing along S-surfaces for tracers */
#define LMD_MIXING      /* Large/McWilliams/Doney mixing */
```

---

## 11. Execution

### Serial
```bash
./romsS < roms.in > roms.log 2>&1
```

### Parallel (MPI)
```bash
mpirun -np 8 ./romsM roms.in > roms.log 2>&1
```

The number of MPI processes must equal `NtileI × NtileJ` as set in `roms.in`.

---

## 12. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for full details. Key failure modes:

| ID | Symptom | Root Cause | Severity |
|----|---------|------------|----------|
| dt_001 | Unrealistic precipitation | Rain in mm/day not kg/m²/s | SILENT |
| dt_002 | Model blows up at start | dt too large for grid/depth | FATAL |
| dt_003 | Wrong sign surface heat flux | Shortwave sign convention | SILENT |
| dt_004 | No tidal signal | Time units mismatch | SILENT |
| dt_005 | All land (mask=0 everywhere) | Bathymetry h negative | FATAL |
| dt_006 | Boundary instabilities | Nudging too strong (Tnudg<1d) | DEGRADED |
| dt_007 | Unrealistic SST | Humidity units wrong | SILENT |

---

## 13. File Structure

```
ki/
├── SKILL.md                          # This file
├── tools/
│   ├── build_roms_grid.py            # Grid builder
│   ├── convert_forcing.py            # Forcing/IC/BC converter
│   ├── run_roms.py                   # Execution wrapper
│   └── parse_roms_output.py          # Output parser
├── docs/
│   ├── s0_grid_generation.md         # Grid setup skill
│   ├── s1_cpp_configuration.md       # CPP flags skill
│   ├── s2_atmospheric_forcing.md     # Met forcing skill
│   ├── s3_initial_boundary.md        # IC/BC skill
│   ├── s4_execution.md               # Model execution skill
│   ├── s5_postprocessing.md          # Output analysis skill
│   └── s6_validation.md              # Validation skill
└── diagnostics/
    └── triplets.yaml                 # Symptom→diagnosis→remedy
```

---

## 14. Quick Start

```bash
# 1. Build ROMS for upwelling test case
cd /path/to/roms && mkdir build && cd build
cmake .. -DAPP=UPWELLING
make -j$(nproc)

# 2. Copy input file
cp ../User/External/roms_upwelling.in roms.in

# 3. Edit roms.in: set VARNAME, GRDNAME, etc.
# (upwelling uses analytical functions, no external files needed)

# 4. Run
./romsS < roms.in > roms.log 2>&1

# 5. Check output
ncdump -h roms_his.nc | head -50

# 6. Validate: expect coastal upwelling, Ekman transport
python3 tools/parse_roms_output.py --input roms_his.nc --variable temp --output temp_timeseries.csv
```
