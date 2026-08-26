---
name: mom6
description: >-
  MOM6. Covers Ocean general circulation (horizontal velocity u, v); Ocean thermodynamics
  (temperature, salinity transport: advection + diffusion); Free-surface / sea surface
  height evolution (split barotropic mode); Layer thickness evolution under the
  generalized ALE vertical coordinate; Mixed-layer and boundary-layer dynamics (ePBL /
  KPP). Use when the task involves running, configuring, calibrating or interpreting MOM6.
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

# MOM6 Ocean Model — Knowledge Infrastructure

## 1. Model Overview

**MOM6** (Modular Ocean Model, version 6) is a numerical ocean model developed by
NOAA-GFDL for simulating large-scale ocean circulation, thermodynamics, and tracer
transport. It solves the hydrostatic primitive equations on an Arakawa C-grid using
the Arbitrary Lagrangian-Eulerian (ALE) vertical coordinate framework.

| Property            | Value                                          |
|---------------------|------------------------------------------------|
| Developer           | NOAA-GFDL (Geophysical Fluid Dynamics Lab)     |
| Language            | Fortran 90/95 + C (FMS infrastructure)         |
| License             | LGPL v3                                        |
| Repository          | https://github.com/NOAA-GFDL/MOM6              |
| Documentation       | https://mom6.readthedocs.io                    |
| Build System        | Autoconf + Make (with FMS dependency)          |
| Parallelism         | MPI domain decomposition + optional OpenMP     |
| I/O Format          | NetCDF4 (via FMS I/O layer)                    |
| Vertical Coordinate | ALE: z*, sigma, isopycnal, hybrid              |
| Horizontal Grid     | Arakawa C-grid (structured, curvilinear)       |
| Time Integration    | Split-explicit barotropic/baroclinic RK2       |

### Key Capabilities
- Global and regional ocean simulations
- Coupled (CESM/UFS via NUOPC/ESMF) or standalone (solo_driver) execution
- Flexible vertical coordinates (ALE regridding/remapping)
- Multiple equations of state (TEOS10, Wright, UNESCO, linear)
- Comprehensive parameterization suite (mesoscale eddies, KPP, tidal mixing)
- Ice shelf interactions and sea-ice coupling
- Passive and biogeochemical tracer transport
- Data assimilation hooks (ODA framework)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## 2. Installation and Build

### 2.1 Dependencies

| Dependency     | Version    | Purpose                              |
|----------------|------------|--------------------------------------|
| Fortran compiler | GFortran 9+ or Intel | Core compilation              |
| MPI            | OpenMPI/MPICH | Domain-decomposed parallelism     |
| netCDF-Fortran | 4.5+       | I/O for grid, forcing, output files  |
| netCDF-C       | 4.7+       | Underlying C library for netCDF      |
| FMS            | 2023.03+   | GFDL framework (diagnostics, I/O)    |
| autoconf       | 2.69+      | Build configuration                  |
| mkmf           | latest     | GFDL Makefile generator              |

### 2.2 Build Steps (Ocean-Only)

```bash
# 1. Clone with submodules
git clone --recursive https://github.com/NOAA-GFDL/MOM6.git
cd MOM6

# 2. Build FMS dependency
cd ac/deps
make -j

# 3. Configure MOM6
cd ../../ac
autoreconf -i
mkdir -p ../build && cd ../build
../ac/configure --with-driver=solo_driver

# 4. Compile
make -j $(nproc)
# Output: build/MOM6
```

### 2.3 Build Variants

| Variant      | Flag                          | Use Case                    |
|--------------|-------------------------------|-----------------------------|
| Symmetric    | (default)                     | Production runs             |
| Asymmetric   | `--enable-asymmetric`         | Reduced memory footprint    |
| OpenMP       | `--enable-openmp`             | Shared-memory parallelism   |
| FMS_cap      | `--with-driver=FMS_cap`       | Coupled model integration   |
| NUOPC        | `--with-driver=nuopc_cap`     | CESM/UFS coupling           |
| Unit tests   | `--with-driver=unit_tests`    | Component testing           |

---

## 3. Pipeline Stages

### Stage 0: Grid Generation
Create the horizontal grid (supergrid) and vertical coordinate definition.
- **Input**: Domain bounds (lat/lon), resolution, projection type
- **Output**: `INPUT/ocean_hgrid.nc` (supergrid), `INPUT/vcoord.nc`
- **Key params**: NIGLOBAL, NJGLOBAL, NK, GRID_CONFIG

### Stage 1: Topography / Bathymetry
Prepare ocean bottom depth from global datasets (GEBCO, ETOPO, SRTM).
- **Input**: Global bathymetry NetCDF, land-sea mask
- **Output**: `INPUT/topog.nc` (variable: `depth` in meters)
- **Key params**: TOPO_FILE, TOPO_VARNAME, MINIMUM_DEPTH, MAXIMUM_DEPTH
- **Trap**: Depth must be positive-down (meters). Negative values = land.

### Stage 2: Atmospheric Forcing
Convert atmospheric reanalysis (ERA5, JRA55, CORE) to MOM6 surface boundary.
- **Input**: Wind stress, heat flux, freshwater flux, radiation
- **Output**: Forcing NetCDF files referenced in MOM_input
- **Key params**: WIND_CONFIG, BUOY_CONFIG, FORCING_FILE
- **Units**: Wind stress [Pa], heat flux [W/m²], precip [kg/m²/s]

### Stage 3: Initial Conditions
Set initial temperature, salinity, and velocity fields.
- **Input**: Climatology (WOA, PHC) or restart file
- **Output**: `INPUT/MOM_IC.nc` or `RESTART/MOM.res.nc`
- **Key params**: TS_CONFIG, TEMP_FILE, SALT_FILE, T_REF, S_REF

### Stage 4: Open Boundary Conditions (Optional)
Prescribe lateral boundary data for regional domains.
- **Input**: Parent model output or reanalysis on boundary segments
- **Output**: `INPUT/OBC_*.nc` files per boundary segment
- **Key params**: OBC_SEGMENT_*, REENTRANT_X, REENTRANT_Y

### Stage 5: Parameter Configuration
Write MOM_input, MOM_override, input.nml, and diag_table.
- **Input**: All upstream outputs, physics choices
- **Output**: `MOM_input`, `MOM_override`, `input.nml`, `diag_table`
- **Key params**: DT, DT_THERM, NK, EQUATION_OF_STATE, COORD_CONFIG

### Stage 6: Model Execution
Run the MOM6 binary with MPI.
- **Input**: All config and data files in run directory
- **Output**: `ocean.stats`, diagnostic NetCDF files, `RESTART/`
- **Command**: `mpirun -np N ./MOM6`

### Stage 7: Output Analysis
Extract and analyze model diagnostics.
- **Input**: Diagnostic NetCDF files, `ocean.stats`
- **Output**: CSV timeseries, validation metrics, figures
- **Variables**: temp, salt, ssh, u, v, KE, PE, MLD

---

## 4. Unit Trap Table

Units are the most common source of silent errors. MOM6 uses SI internally but
input data often arrives in different units.

| Variable           | MOM6 Internal Unit     | Common Source Unit    | Conversion Factor        | Trap ID |
|--------------------|------------------------|-----------------------|--------------------------|---------|
| Temperature        | degC (potential)       | K (Kelvin)            | T_C = T_K - 273.15      | dt_001  |
| Temperature        | Conservative (TEOS10)  | Potential temp        | Use gsw_CT_from_pt()     | dt_002  |
| Salinity           | PSU (practical)        | g/kg (absolute)       | S_psu ≈ S_abs / 1.00472  | dt_003  |
| Salinity           | PSU                    | ppm                   | S_psu = S_ppm / 1000     | dt_004  |
| Depth/Topography   | m (positive down)      | m (positive up)       | depth = -elevation       | dt_005  |
| Thickness (Bouss.) | m                      | kg/m²                 | h_m = h_kgm2 / rho_0    | dt_006  |
| Wind stress        | Pa (N/m²)             | dyn/cm²               | tau_Pa = tau_dyn * 0.1   | dt_007  |
| Heat flux          | W/m² (+ into ocean)   | W/m² (+ out of ocean) | Q_in = -Q_out            | dt_008  |
| Precipitation      | kg/m²/s               | mm/day                | P = P_mm / 86400         | dt_009  |
| Pressure           | Pa                     | dbar                  | P_Pa = P_dbar * 1e4      | dt_010  |
| Evaporation        | kg/m²/s (negative)    | mm/day (positive)     | E = -E_mm / 86400        | dt_011  |
| Shortwave rad.     | W/m² (+ into ocean)   | W/m² (+ downward)     | Usually same sign        | dt_012  |
| Longwave rad.      | W/m² (net, + into)    | W/m² (downwelling)    | LW_net = LW_down - ε σ T⁴| dt_013  |
| Time step (DT)     | seconds                | hours/minutes         | DT_s = DT_h * 3600      | dt_014  |
| Coriolis           | s⁻¹                   | rad/s                 | Same unit                | dt_015  |

---

## 5. Configuration Reference

### 5.1 MOM_input Key Parameters

```fortran
! --- Grid ---
NIGLOBAL = 360            ! Global grid points in x [count]
NJGLOBAL = 180            ! Global grid points in y [count]
NK = 75                   ! Number of vertical layers [count]
NIHALO = 4                ! Halo width x [count]
NJHALO = 4                ! Halo width y [count]

! --- Time Stepping ---
DT = 900.0                ! Baroclinic dynamics timestep [s]
DT_THERM = 3600.0         ! Thermodynamics timestep [s]
DTBT = -0.98              ! Barotropic timestep [s]; negative = auto CFL
BE = 0.6                  ! Barotropic time-stepping implicitness [nondim]

! --- Physics ---
EQUATION_OF_STATE = "WRIGHT"  ! EOS choice: WRIGHT, TEOS10, UNESCO, LINEAR
RHO_0 = 1035.0            ! Reference density [kg/m³]
C_P = 3925.0              ! Heat capacity [J/(degC·kg)]
G_EARTH = 9.80            ! Gravitational acceleration [m/s²]
ENABLE_THERMODYNAMICS = True

! --- Vertical Coordinate ---
COORD_CONFIG = "file"     ! Vertical coordinate source
REGRIDDING_COORDINATE_MODE = "ZSTAR"  ! ALE target: ZSTAR, SIGMA, RHO, HYCOM
ALE_COORDINATE_CONFIG = "FILE:vcoord.nc,interfaces=zeta"

! --- Lateral Mixing ---
LAPLACIAN = True          ! Laplacian horizontal viscosity
KH = 600.0               ! Horizontal viscosity [m²/s]
SMAGORINSKY_AH = True     ! Smagorinsky biharmonic viscosity
SMAG_BI_CONST = 0.06      ! Smagorinsky coefficient [nondim]
THICKNESSDIFFUSE = True    ! GM thickness diffusion

! --- Vertical Mixing ---
KD = 1.0e-5              ! Background diapycnal diffusivity [m²/s]
KV = 1.0e-4              ! Background kinematic viscosity [m²/s]
BOTTOMDRAGLAW = True       ! Quadratic bottom drag
CDRAG = 0.003              ! Bottom drag coefficient [nondim]
BULKMIXEDLAYER = False     ! Use KPP instead
USE_KPP = True             ! KPP boundary layer scheme

! --- I/O ---
ENERGYSAVEDAYS = 1.0       ! Energy stats output interval [days]
RESTINT = 365.0            ! Restart write interval [days]
RESTART_CONTROL = 3        ! 1=generic, 2=timestamped, 3=both
SAVE_INITIAL_CONDS = True  ! Save IC file
```

### 5.2 input.nml Key Namelists

```fortran
&ocean_solo_nml
  months = 0
  days = 365
  hours = 0
  date_init = 1990, 1, 1, 0, 0, 0
  calendar = 'NOLEAP'
/

&MOM_input_nml
  output_directory = './'
  input_filename = 'n'        ! 'n' = new run, 'r' = restart
  parameter_filename = 'MOM_input', 'MOM_override'
/

&diag_manager_nml
  max_axes = 100
  max_num_axis_sets = 50
  max_files = 40
  max_output_fields = 300
/

&fms_nml
  domains_stack_size = 710000
  stack_size = 0
/
```

### 5.3 diag_table Format

```
"MOM6 Diagnostics"
1990 1 1 0 0 0

"ocean_daily",   1, "days",  1, "days", "time"
"ocean_month",  30, "days",  1, "days", "time"
"ocean_annual",365, "days",  1, "days", "time"

# field_name, module, output_file, time_sampling, reduction, regional, packing
"temp",  "ocean_model", "ocean_daily", "all", .true., "none", 2
"salt",  "ocean_model", "ocean_daily", "all", .true., "none", 2
"ssh",   "ocean_model", "ocean_daily", "all", .true., "none", 2
"u",     "ocean_model", "ocean_month", "all", .true., "none", 2
"v",     "ocean_model", "ocean_month", "all", .true., "none", 2
"KE",    "ocean_model", "ocean_month", "all", .true., "none", 2
"MLD_003","ocean_model","ocean_month", "all", .true., "none", 2
```

---

## 6. Key Variables and Diagnostics

### 6.1 Prognostic Variables (State)

| Variable | Symbol | Units      | Grid Point | Description                    |
|----------|--------|------------|------------|--------------------------------|
| temp     | T      | degC       | T-point    | Potential/conservative temp    |
| salt     | S      | PSU/g·kg⁻¹| T-point    | Practical/absolute salinity    |
| h        | h      | m          | T-point    | Layer thickness                |
| u        | u      | m/s        | u-point    | Zonal velocity                 |
| v        | v      | m/s        | v-point    | Meridional velocity            |

### 6.2 Key Diagnostic Variables

| Variable   | Units   | Description                            |
|------------|---------|----------------------------------------|
| ssh        | m       | Sea surface height (dynamic)           |
| SST        | degC    | Sea surface temperature                |
| SSS        | PSU     | Sea surface salinity                   |
| MLD_003    | m       | Mixed layer depth (0.03 kg/m³ crit.)   |
| KE         | m²/s²   | Kinetic energy per unit mass           |
| PE_to_KE   | W/m²    | PE-to-KE conversion rate               |
| uh         | m³/s    | Zonal volume flux                      |
| vh         | m³/s    | Meridional volume flux                 |
| e          | m       | Interface heights (layer boundaries)   |
| Kd_itides  | m²/s    | Internal-tide driven diffusivity       |

### 6.3 ocean.stats Format

```
  Step, Day, Truncs, Energy/Mass, Maximum CFL, Mean Sea Level, ...
     0,   0.000,  0, En 0.0000000E+00, CFL  0.000, SL -0.000E+00, ...
    96,   1.000,  0, En 1.2345678E-04, CFL  0.123, SL  1.234E-03, ...
```

---

## 7. Equation of State Options

| EOS Name | Parameter String | Input T Type       | Input S Type         | Accuracy |
|----------|------------------|--------------------|----------------------|----------|
| TEOS10   | `"TEOS10"`       | Conservative [degC]| Absolute [g/kg]      | Highest  |
| Wright   | `"WRIGHT"`       | Potential [degC]   | Practical [PSU]      | High     |
| UNESCO   | `"UNESCO"`       | Potential [degC]   | Practical [PSU]      | Standard |
| Linear   | `"LINEAR"`       | Any [degC]         | Any [PSU]            | Lowest   |

**Critical trap**: If EQUATION_OF_STATE = "TEOS10", temperature MUST be conservative
temperature and salinity MUST be absolute salinity. Using potential temperature with
TEOS10 introduces a ~0.2 degC bias that is nearly invisible in short runs but
accumulates over decades.

---

## 8. Vertical Coordinate Modes

| Mode     | Config String | Description                              | Best For           |
|----------|---------------|------------------------------------------|--------------------|
| Z*       | `"ZSTAR"`     | Quasi-geopotential, free surface         | General purpose    |
| Sigma    | `"SIGMA"`     | Terrain-following                        | Shallow coastal    |
| RHO      | `"RHO"`       | Isopycnal (density-following)            | Deep ocean         |
| HYCOM    | `"HYCOM1"`    | Hybrid isopycnal-z                       | Global production  |
| Sigma-z  | `"SIGMA_SHELF_ZSTAR"` | Sigma nearshore, z* offshore    | Coastal-open ocean |

---

## 9. Common Workflows

### 9.1 Quick Smoke Test (Solo Driver)

```bash
cd run_directory
ln -s /path/to/build/MOM6 .
# Place MOM_input, input.nml, diag_table, INPUT/ files
mpirun -np 4 ./MOM6
# Check ocean.stats for energy conservation
```

### 9.2 Restart a Simulation

```bash
# In input.nml, change:
#   input_filename = 'r'   (was 'n')
# Copy RESTART/*.nc to INPUT/
cp RESTART/MOM.res.nc INPUT/
mpirun -np 4 ./MOM6
```

### 9.3 Regional Downscaling

1. Generate regional grid with FRE-NCtools or gridtools-py
2. Cut topography from GEBCO to regional domain
3. Extract OBC segments from parent model
4. Set OBC_SEGMENT_* parameters in MOM_input
5. Run with `REENTRANT_X = False, REENTRANT_Y = False`

---

## 10. Tool Reference

| Tool Script                  | Stage | Purpose                                    |
|------------------------------|-------|--------------------------------------------|
| `forcing_converter.py`       | S2    | Convert atmospheric forcing to MOM6 NetCDF |
| `topography_converter.py`    | S1    | Process bathymetry for MOM6 grid           |
| `run_mom6.py`                | S6    | Execute MOM6 with preflight checks         |
| `output_parser.py`           | S7    | Parse diagnostics to CSV + compute metrics |

All tools follow the **validate → process → validate** pattern:
1. **Pre-validate**: Check input file existence, variable names, units
2. **Process**: Perform conversion/execution with unit safeguards
3. **Post-validate**: Verify output integrity, physical bounds, NaN checks

---

## 11. Physical Bounds for Validation

| Variable        | Valid Range           | Alarm Threshold       |
|-----------------|------------------------|-----------------------|
| Temperature     | -2.0 to 40.0 degC    | < -3 or > 42 degC    |
| Salinity        | 0.0 to 42.0 PSU      | < -0.1 or > 50 PSU   |
| SSH             | -10.0 to 10.0 m      | |SSH| > 15 m          |
| Velocity (u,v)  | -5.0 to 5.0 m/s      | |vel| > 8 m/s         |
| Layer thickness | 0.0 to 8000.0 m      | h < -0.001 m         |
| MLD             | 0.0 to 5000.0 m      | MLD > depth           |
| KE              | 0.0 to 10.0 m²/s²    | KE > 20 m²/s²        |
| Bottom drag     | 0.001 to 0.01 nondim  | > 0.05               |

---

## 12. Failure Domains

1. **Unit Conversion**: Temperature K↔C, salinity PSU↔g/kg, depth sign, flux sign
2. **Grid Mismatch**: Symmetric vs asymmetric, halo size, domain decomposition
3. **EOS Mismatch**: Wrong T/S type for chosen equation of state
4. **Timestep Instability**: CFL violation, barotropic blowup, negative thickness
5. **I/O Errors**: Missing INPUT files, wrong variable names, dimension mismatch
6. **Forcing Errors**: Temporal interpolation gaps, land-sea mask inconsistency
