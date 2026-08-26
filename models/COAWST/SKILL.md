---
name: coawst
description: >-
  COAWST v3.8. Covers Two-way coupled coastal-ocean circulation (3D temperature, salinity,
  velocity, free surface) via…; Nearshore spectral wind-wave evolution and wave-current
  interaction via SWAN; Mesoscale atmospheric forcing and air-sea feedback via WRF;
  Wave-current driven sediment resuspension, transport, and bed morphodynamics. Use when
  the task involves running, configuring, calibrating or interpreting COAWST.
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

# COAWST Knowledge Infrastructure

| Field             | Value                                                        |
|-------------------|--------------------------------------------------------------|
| **Package**       | COAWST KI v1.0                                               |
| **Model**         | COAWST v3.8 (Coupled-Ocean-Atmosphere-Wave-Sediment Transport) |
| **Authors**       | John C. Warner (USGS), Brandy Armstrong, Ruoying He, Jesse Maitland |
| **Repository**    | https://github.com/DOI-USGS/COAWST                          |
| **Language**      | Fortran 90+ (2938 files), C (1142), MATLAB (572)             |
| **Build**         | GNU Make / CMake with MPI                                    |
| **Validation**    | Hurricane Sandy (2012), Inlet Test, Delilah morphodynamics   |
| **KI Lines**      | ~4,200 (tools) + 400 (SKILL) + 600 (docs)                   |

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/NOAA_Tides/SKILL.md` for tidal observation data.
See `data_ki/NDBC/SKILL.md` for wave buoy observations.


## 1. Overview

COAWST is a coupled numerical modelling system that combines:

- **ROMS** (Regional Ocean Modeling System) — 3D ocean circulation, temperature, salinity, sediment transport
- **SWAN** (Simulating WAves Nearshore) — spectral wave propagation and transformation
- **WRF** (Weather Research and Forecasting) — mesoscale atmospheric modelling
- **WW3** (WAVEWATCH III) — open-ocean wave modelling (alternative to SWAN)
- **CICE** — sea-ice dynamics (optional)
- **InWave** — infragravity wave modelling (optional)

Models are coupled via the **Model Coupling Toolkit (MCT)** or **ESMF/NUOPC** framework, exchanging fields (SST, wind stress, wave height, currents) at user-defined intervals through SCRIP-weighted regridding.

### Key Differentiators from Standalone ROMS
- Full two-way atmosphere-ocean-wave coupling
- Wave-current interaction (radiation stress, Stokes drift, wave-enhanced bottom stress)
- Sediment transport with morphological evolution
- Vegetation and marsh dynamics modules
- Wetting/drying for coastal inundation

---

## 2. Installation

### Dependencies (Required)
| Library       | Version   | Purpose                              |
|---------------|-----------|--------------------------------------|
| NetCDF-4      | ≥4.6      | All I/O (grid, forcing, output)      |
| HDF5          | ≥1.10     | NetCDF-4 backend                     |
| MPI           | Any       | Parallel execution (OpenMPI, MPICH)  |
| Fortran 90+   | gfortran/ifort | Compilation                     |
| GNU Make      | ≥3.80     | Build system                         |
| Perl          | ≥5        | Dependency fixing scripts            |

### Dependencies (Optional)
| Library       | Purpose                                      |
|---------------|----------------------------------------------|
| MCT           | Model Coupling Toolkit (included in Lib/MCT) |
| SCRIP         | Regridding weights (included in Lib/SCRIP_COAWST) |
| WRF           | Atmospheric model coupling                   |
| ARPACK        | Generalized Stability Theory analysis        |
| SCORPIO/PIO   | Parallel I/O                                 |

### Build Procedure
```bash
# 1. Edit build_coawst.sh — set FORT, ROMS_APPLICATION, paths
export FORT=gfortran
export ROMS_APPLICATION=SANDY

# 2. Build (GNU Make)
./build_coawst.sh

# 3. Or CMake
mkdir build && cd build
cmake .. -DROMS_APPLICATION=SANDY
make -j8

# 4. Binary produced: coawstM (coupled) or romsM (standalone ROMS)
```

### Quick Validation
```bash
cd Projects/Inlet_test/Coupled
mpirun -np 4 ../../../coawstM ocean_inlet_test.in
# Expect: history NetCDF files, no BLOWUP
```

---

## 3. Pipeline Stages

| Stage | Name                  | Description                                   | Depends On | Key Tool              |
|-------|-----------------------|-----------------------------------------------|------------|-----------------------|
| s0    | Configuration         | Select application, set CPP flags              | —          | (manual)              |
| s1    | Grid Generation       | Create ROMS grid (bathymetry, mask, coords)    | s0         | `convert_grid.py`     |
| s2    | Forcing Preparation   | Convert atmospheric/tidal forcing to NetCDF    | s0         | `convert_forcing.py`  |
| s3    | Initial Conditions    | Create initial temperature/salinity/velocity   | s1         | `convert_forcing.py`  |
| s4    | Boundary Conditions   | Create open boundary files from parent model   | s1         | `convert_forcing.py`  |
| s5    | Coupling Setup        | Generate SCRIP weights, coupling.in            | s1         | `generate_config.py`  |
| s6    | Namelist Generation   | Create ocean.in, swan.in, wrf namelist files   | s1-s5      | `generate_config.py`  |
| s7    | Compilation           | Build coawstM binary                           | s0         | `run_coawst.py`       |
| s8    | Execution             | Run coupled simulation                         | s6, s7     | `run_coawst.py`       |
| s9    | Output Analysis       | Extract time series, compute diagnostics       | s8         | `parse_output.py`     |
| s10   | Validation            | Compare to observations, compute metrics       | s9         | `parse_output.py`     |

**Parallelism:** s1, s2, s7 can run concurrently. s3-s4 depend on s1. s6 depends on s1-s5.

---

## 4. Unit Trap Table

These are the most dangerous unit mismatches — they produce **silent errors** (model runs but gives wrong results).

| ID      | Variable            | External Unit       | COAWST Internal Unit | Factor       | Failure If Wrong                          |
|---------|---------------------|---------------------|----------------------|--------------|-------------------------------------------|
| ut_001  | Temperature         | K (some reanalysis) | °C                   | −273.15      | Unrealistic SST, density blowup           |
| ut_002  | Wind stress (sustr) | Pa (N/m²)           | m²/s²                | ÷ ρ₀ (1025)  | Currents 1000× too strong                 |
| ut_003  | Heat flux (srflx)   | W/m²                | °C m/s               | ÷(ρ₀·Cp)    | Thermal stratification wildly wrong       |
| ut_004  | Salinity            | g/kg                | PSU (dimensionless)  | ~1:1         | OK if PSS-78 scale; check range 0-42      |
| ut_005  | Precipitation       | mm/day              | m/s                  | ÷86400000    | Freshwater flux 1000× too high            |
| ut_006  | Sea level (zeta)    | cm                  | m                    | ÷100         | Boundary blowup, CFL violation            |
| ut_007  | Wave direction      | degrees (met conv)  | radians (math conv)  | ×π/180+rot   | Wave-current stress in wrong direction    |
| ut_008  | Air pressure        | hPa (mb)            | mb (same)            | 1:1          | OK — but Pa needs ÷100                    |
| ut_009  | River discharge     | m³/day              | m³/s                 | ÷86400       | Estuary salinity completely wrong         |
| ut_010  | Bottom roughness    | mm                  | m                    | ÷1000        | Bottom stress orders of magnitude off     |
| ut_011  | Humidity            | % (RH)              | kg/kg (specific)     | Convert      | Latent heat flux wrong, evap errors       |
| ut_012  | Bathymetry          | positive up          | positive down (h>0)  | ×(−1)        | Grid above water, instant crash           |

---

## 5. Critical Domain Knowledge

**dk_001: S-coordinate vertical system.**
ROMS uses terrain-following S-coordinates, not z-levels. Parameters `theta_s`, `theta_b`, `Tcline`, and `Vstretching` control vertical resolution. Wrong stretching → poor resolution at thermocline → degraded mixing.

**dk_002: Staggered Arakawa-C grid.**
Variables live on different grid points: ρ (tracers, SSH), u (east velocity), v (north velocity), ψ (vorticity). Grid dimensions differ: if ρ-grid is (Lm+2)×(Mm+2), u-grid is (Lm+1)×(Mm+2). Forcing/BC files must match the correct staggering.

**dk_003: Time reference.**
All `ocean_time` values in NetCDF files are **seconds since a reference date** (set via `TIME_REF` in ocean.in). Mismatched reference dates between forcing and model cause temporal interpolation to use wrong data or extrapolate to NaN.

**dk_004: Coupling interval sizing.**
Coupling intervals (e.g., `TI_OCN2WAV = 600` seconds) must be integer multiples of both the ocean and wave model timesteps. Non-integer ratios cause desynchronization and data gaps.

**dk_005: Tiling and processor layout.**
`NtileI × NtileJ` must equal the MPI processor count. Mismatch → immediate crash or deadlock. Tile dimensions should roughly match grid aspect ratio for load balance.

**dk_006: BULK_FLUXES vs prescribed fluxes.**
If `BULK_FLUXES` CPP flag is defined, ROMS computes heat/momentum fluxes internally from atmospheric variables (wind, temperature, humidity). If not defined, ROMS expects pre-computed fluxes (stress, heat flux). Providing the wrong type → double-counting or missing forcing.

**dk_007: Wet/dry masking.**
When `WET_DRY` is enabled, cells can dynamically flood/dry. Initial SSH must be consistent with bathymetry — cells with h + zeta < Dcrit are masked dry. Inconsistent initialization → checkerboard instabilities.

**dk_008: SWAN spectral resolution.**
SWAN direction bins and frequency bins must be sufficient for the physics. Too few direction bins (< 24) smears directional spreading; too few frequencies (< 25) misses swell-sea separation.

**dk_009: Radiation open boundary conditions.**
Radiation+Nudging (`RadNud`) boundaries require nudging timescales (`obcfac`) — too small → reflections; too large → boundary data ignored. Typical: 1-3 days for tracers, 0.5-1 day for 2D momentum.

---

## 6. Input File Formats

### Configuration Files (.in)
- **ocean_*.in**: ROMS parameters (grid dims, timestep, physics, I/O paths)
- **coupling_*.in**: MCT coupling intervals, processor allocation, SCRIP weights
- **swan_*.in**: SWAN spectral parameters, physics switches
- **namelist.input**: WRF atmospheric configuration
- **Format**: `KEYWORD = value` (ROMS), Fortran namelist (WRF), SWAN command syntax

### NetCDF Input Files
| File Type       | Key Variables                                      | Dimensions                    |
|-----------------|----------------------------------------------------|-------------------------------|
| Grid            | lon_rho, lat_rho, h, mask_rho, angle, f, pm, pn    | xi_rho × eta_rho             |
| Initial         | temp, salt, u, v, ubar, vbar, zeta                  | xi × eta × s_rho × time     |
| Forcing         | Uwind, Vwind, Tair, Pair, Qair, rain, swrad, lwrad | xi_rho × eta_rho × time     |
| Boundary        | temp_north, salt_south, u_west, zeta_east, etc.     | boundary × s_rho × time     |
| Tidal           | tide_Eamp, tide_Ephase, tide_Cangle, tide_Cphase   | xi × eta × tide_period      |
| SCRIP weights   | src_address, dst_address, remap_matrix              | n_s (sparse matrix)         |

---

## 7. Output File Formats

All outputs are **NetCDF-4** with CF-1.6 conventions.

| File               | Contents                                   | Frequency       |
|--------------------|--------------------------------------------|-----------------|
| `*_his_*.nc`       | History snapshots (full 3D state)          | Every NHIS dt   |
| `*_avg_*.nc`       | Time-averaged fields                       | Every NAVG dt   |
| `*_rst_*.nc`       | Restart/checkpoint                         | Every NRST dt   |
| `*_dia_*.nc`       | Diagnostic terms (momentum/tracer budgets) | Every NDIA dt   |
| `*_sta_*.nc`       | Station time series (selected points)      | Every NSTA dt   |
| `*_flt_*.nc`       | Lagrangian float trajectories              | Every NFLT dt   |
| `*_qck_*.nc`       | Quick-save 2D surface fields               | Every NQCK dt   |

### Key Output Variables
| Variable  | Long Name                    | Units   | Grid   |
|-----------|------------------------------|---------|--------|
| zeta      | Free-surface elevation       | m       | rho    |
| temp      | Potential temperature        | °C      | rho    |
| salt      | Salinity                     | PSU     | rho    |
| u / v     | Velocity components          | m/s     | u / v  |
| ubar/vbar | Barotropic velocity          | m/s     | u / v  |
| Hsig      | Significant wave height      | m       | rho    |
| AKv       | Vertical viscosity           | m²/s    | w      |
| AKt       | Vertical diffusivity (temp)  | m²/s    | w      |
| bed_thickness | Sediment bed thickness   | m       | rho    |

---

## 8. Tools Reference

| Tool                  | Script                  | Purpose                                        | Lines |
|-----------------------|-------------------------|-------------------------------------------------|-------|
| Forcing converter     | `convert_forcing.py`    | ERA5/GFS/NARR → ROMS NetCDF forcing            | ~550  |
| Grid converter        | `convert_grid.py`       | Bathymetry + coastline → ROMS grid NetCDF      | ~450  |
| Config generator      | `generate_config.py`    | Generate ocean.in, coupling.in from parameters  | ~500  |
| Execution wrapper     | `run_coawst.py`         | Preflight checks, mpirun, output validation     | ~300  |
| Output parser         | `parse_output.py`       | History/station NetCDF → CSV + metrics          | ~400  |

---

## 9. Calibration Parameters

| Parameter       | ocean.in Keyword | Range          | Sensitivity | Description                         |
|-----------------|------------------|----------------|-------------|-------------------------------------|
| theta_s         | THETA_S          | 0.1 – 10.0    | High        | Surface S-coord stretching          |
| theta_b         | THETA_B          | 0.0 – 4.0     | High        | Bottom S-coord stretching           |
| Tcline          | TCLINE           | 10 – 300 m    | Medium      | Thermocline depth for stretching    |
| DT              | DT               | 1 – 300 s     | High        | Baroclinic timestep                 |
| NDTFAST         | NDTFAST           | 10 – 60       | High        | Barotropic:baroclinic ratio         |
| Znudg           | ZNUDG            | 0.01 – 30 day | Medium      | Free-surface nudging timescale      |
| Tnudg           | TNUDG            | 1 – 360 day   | Medium      | Tracer nudging timescale            |
| VISC2           | VISC2            | 1 – 100 m²/s  | Medium      | Horizontal Laplacian viscosity      |
| TNU2            | TNU2             | 0 – 50 m²/s   | Medium      | Horizontal tracer diffusion         |
| rdrg2           | RDRG2            | 1e-4 – 1e-2   | High        | Quadratic bottom drag coefficient   |
| Vtransform      | Vtransform       | 1 or 2        | High        | S-coordinate transformation type    |
| Vstretching     | Vstretching      | 1 – 5         | High        | S-coordinate stretching function    |

---

## 10. Coupling Points

| Source | Target | Variables Exchanged                              | Interval     |
|--------|--------|--------------------------------------------------|--------------|
| WRF    | ROMS   | Wind (U10, V10), Tair, Pair, Qair, rain, swrad  | 60–600 s     |
| ROMS   | WRF    | SST, sea-ice fraction                            | 60–600 s     |
| SWAN   | ROMS   | Hsig, Dir, Period, orbital velocity, dissipation | 60–600 s     |
| ROMS   | SWAN   | SSH (zeta), currents (u, v), bathymetry update   | 60–600 s     |
| WRF    | SWAN   | Wind (U10, V10)                                  | 60–600 s     |
| SWAN   | WRF    | Wave roughness (Charnock)                        | 60–600 s     |

---

## 11. Data Requirements

| Data                | Source Examples                  | Format    | Resolution     |
|---------------------|----------------------------------|-----------|----------------|
| Bathymetry          | GEBCO, ETOPO, SRTM30+           | NetCDF    | 15" – 1'       |
| Coastline           | GSHHS                           | Shapefile | Various        |
| Atmospheric forcing | ERA5, GFS, NARR, CFSR           | GRIB/NC   | 0.25° – 32 km  |
| Ocean IC/BC         | HYCOM, GLORYS, SODA             | NetCDF    | 1/12° – 1/4°   |
| Tidal constituents  | TPXO, FES2014, OTPS             | NetCDF    | 1/6° – 1/30°   |
| River discharge     | USGS, GRDC                      | CSV/NC    | Daily           |
| Wave spectra (BC)   | WW3 global hindcast             | NetCDF    | 0.5°            |
| SST observations    | GHRSST, AVHRR, OSTIA            | NetCDF    | 1 – 5 km       |

---

## 12. Quick Start Examples

```bash
# 1. Build standalone ROMS (upwelling test)
export ROMS_APPLICATION=UPWELLING
export FORT=gfortran
./build_coawst.sh

# 2. Run upwelling test
mpirun -np 4 ./coawstM ROMS/External/roms_upwelling.in

# 3. Build coupled COAWST (Sandy)
export ROMS_APPLICATION=SANDY
./build_coawst.sh

# 4. Run coupled Sandy simulation
mpirun -np 16 ./coawstM Projects/Sandy/coupling_sandy.in

# 5. Extract SST time series from output
python3 ki/tools/parse_output.py \
  --history Projects/Sandy/sandy_his.nc \
  --variable temp --level surface \
  --output sst_timeseries.csv

# 6. Convert ERA5 forcing
python3 ki/tools/convert_forcing.py \
  --source era5_data/ --target forcing.nc \
  --grid Projects/Sandy/Sandy_roms_grid.nc \
  --type atmospheric --source-format era5
```

---

## 13. Diagnostic Triplets Summary

| ID      | Stage | Severity | Symptom (Short)                          |
|---------|-------|----------|------------------------------------------|
| dt_001  | s2    | silent   | SST diverges — temperature in K not °C   |
| dt_002  | s2    | silent   | Currents 1000× too strong — stress in Pa |
| dt_003  | s2    | fatal    | NaN in forcing — time ref mismatch       |
| dt_004  | s5    | fatal    | Deadlock — NtileI×NtileJ ≠ nprocs       |
| dt_005  | s8    | fatal    | CFL blowup — DT too large               |
| dt_006  | s2    | silent   | Wrong heat flux — bulk vs prescribed     |
| dt_007  | s1    | silent   | Bathymetry sign — positive up vs down    |
| dt_008  | s2    | silent   | Precipitation 1000× — mm vs m           |
| dt_009  | s4    | silent   | BC on wrong stagger — rho vs u/v         |
| dt_010  | s5    | degraded | Coupling desync — non-integer interval   |
| dt_011  | s2    | silent   | Wave dir in degrees not radians          |
| dt_012  | s3    | silent   | IC salinity out of range → density crash |
| dt_013  | s8    | fatal    | Restart time mismatch                    |
| dt_014  | s6    | degraded | Too few SWAN freq bins → missing swell   |
| dt_015  | s2    | silent   | Humidity RH% vs specific kg/kg           |

See `diagnostics/triplets.yaml` for full symptom → diagnosis → remedy chains.

---

## 14. File Structure

```
ki/
├── SKILL.md                          # This file
├── tools/
│   ├── convert_forcing.py            # Atmospheric/tidal forcing converter
│   ├── convert_grid.py               # Grid/bathymetry converter
│   ├── generate_config.py            # ocean.in / coupling.in generator
│   ├── run_coawst.py                 # Execution wrapper
│   └── parse_output.py               # Output parser and metrics
├── docs/
│   ├── s1_grid_generation.md         # Grid creation skill
│   ├── s2_forcing_preparation.md     # Forcing data skill
│   ├── s5_coupling_setup.md          # Coupling configuration skill
│   ├── s8_execution.md               # Model execution skill
│   ├── s9_output_analysis.md         # Output analysis skill
│   └── calibration_guide.md          # Parameter tuning guide
└── diagnostics/
    └── triplets.yaml                 # 15+ symptom→diagnosis→remedy
```
