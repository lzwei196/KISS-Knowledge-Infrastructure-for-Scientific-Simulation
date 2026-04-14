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

# COSIPY v2.0.2 (COupled Snowpack and Ice surface energy and mass balance model in PYthon) — Knowledge Infrastructure

**Package**: `cosipy-ki` v1.0.0
**Model**: COSIPY v2.0.2
**Source**: https://github.com/cryotools/cosipy
**Domain**: Cryosphere — glacier and snowpack energy/mass balance
**Last updated**: 2026-03-26
**Stats**: 4 tools | 6 skill documents | 20 diagnostic triplets | ~2,400 lines of validated Python
**Validation status**: `validated` (Zhadang Glacier, Tibet, ERA5 2009)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for atmospheric forcing documentation.
See `data_ki/SNOTEL/SKILL.md` for snow observations.
See `data_ki/BedMachine/SKILL.md` for ice topography.
See `data_ki/MEaSUREs/SKILL.md` for ice velocity.


## Overview

This knowledge infrastructure enables autonomous simulation of glacier and snowpack energy and mass balance using COSIPY. The tools convert meteorological forcing data, configure simulation parameters, execute the model, and parse outputs — all without manual intervention.

**What COSIPY does**: Coupled surface energy balance and subsurface multi-layer model for glaciers and snowpacks. Simulates:
- Surface energy balance (shortwave, longwave, sensible heat, latent heat, ground heat flux, rain heat)
- Surface mass balance (snowfall accumulation, melt, sublimation, evaporation, deposition, condensation)
- Internal mass balance (refreezing, subsurface melt)
- Adaptive vertical layer system (up to 200 layers: snow + glacier ice)
- Albedo evolution (Oerlemans98, Bougamont05 parameterizations)
- Penetrating shortwave radiation (Bintanja95)
- Snow densification (Boone, empirical, constant methods)
- Heat equation solver (subsurface temperature evolution)
- Percolation and refreezing of meltwater
- Roughness length evolution (Moelg12)

**Key characteristics**:
- Python-based (no Fortran/C compilation needed)
- Uses Dask for distributed computing (LocalCluster or SLURM)
- Configuration via TOML files (config.toml, constants.toml)
- Input/output in netCDF format
- Supports both AWS station data and WRF reanalysis inputs
- Built-in utilities for data conversion (aws2cosipy, wrf2cosipy, create_static_file)

---

## Installation

### From PyPI
```bash
pip install cosipymodel
cosipy-setup   # generate template configuration files
```

### From source (recommended for development)
```bash
git clone https://github.com/cryotools/cosipy.git
cd cosipy
pip install -e .
```

### System dependency
```
GDAL: sudo apt-get install gdal-bin libgdal-dev
```

### Python dependencies
```
numpy>=2.0, pandas>2.0, scipy>=1.1.0, xarray>=0.18.0, xarray-spatial,
netcdf4>=1.5.1.2, distributed, dask, dask-jobqueue, numba, metpy,
matplotlib, nco, cdo, cartopy, vtk
```

### Test data (included in repo)
```
data/input/Zhadang/Zhadang_ERA5_2009.nc    # 240 hourly timesteps, 1x1 grid
data/input/Zhadang/Zhadang_ERA5_2009_2018.csv  # CSV forcing
data/static/Zhadang_static.nc               # DEM, slope, aspect, mask (7x13 grid)
data/input/HEF/HEF_input.nc               # Hintereisferner dataset
data/input/HEF/data_stakes_hef.csv        # Stake validation data
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) / Entry Point | Description |
|---|-------|-----------------------|-------------|
| 0 | Configuration | (manual / `cosipy-setup`) | Select glacier, period, forcing source |
| 1 | Static file | `cosipy-create-static` | Create DEM, slope, aspect, mask from GeoTIFF + shapefile |
| 2 | Forcing conversion | `cosipy-aws2cosipy` / `cosipy-wrf2cosipy` | AWS CSV or WRF output to COSIPY netCDF input |
| 3 | Parameter config | `config.toml` + `constants.toml` | Simulation period, parameterizations, initial conditions |
| 4 | Execution | `python COSIPY.py` / `cosipy-run` | Run energy/mass balance model (Dask parallel) |
| 5 | Output analysis | `cosipy-plot-field` / `cosipy-plot-profile` | Visualize spatial and profile results |
| 6 | Validation | Stake evaluation (built-in) | Compare to stake MB or snow height data |

### Parallelism
- Stages 1 and 2 can run in parallel
- Stage 3 is manual configuration
- Stage 4 depends on 1, 2, 3
- Stages 5 and 6 depend on 4

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing` | s2 | `tools/convert_forcing.py` | Global/ERA5/AWS data to COSIPY netCDF (unit conversions) |
| `convert_static` | s1 | `tools/convert_static.py` | DEM + shapefile to COSIPY static file |
| `run_cosipy` | s4 | `tools/run_cosipy.py` | Execute COSIPY with preflight checks |
| `parse_output` | s5 | `tools/parse_output.py` | Extract COSIPY netCDF results to CSV |

**Total**: 4 tools, ~2,400 lines of validated Python code.

---

## Input Format — Forcing netCDF

The input netCDF file must contain these variables on dimensions `(time, lat, lon)`:

| Variable | Units | Description | Bounds Check |
|----------|-------|-------------|--------------|
| `T2` | K | 2-m air temperature | 223.16 - 316.16 |
| `RH2` | % | 2-m relative humidity | 0 - 100 |
| `U2` | m s^-1 | 2-m wind speed | 0 - 50 |
| `G` | W m^-2 | Incoming shortwave radiation | 0 - 1600 |
| `PRES` | hPa | Surface air pressure | 200 - 1080 |
| `RRR` | mm | Total precipitation (liquid+solid) per time step | 0 - 20 |
| `N` | % (0-1 fraction) | Cloud cover fraction | 0 - 1 |
| `LWin` | W m^-2 | Incoming longwave radiation (optional if N given) | 0 - 400 |
| `SNOWFALL` | m | Snowfall in snow height per time step (optional if RRR given) | 0 - 0.05 |

**Static variables** (no time dimension):

| Variable | Units | Description |
|----------|-------|-------------|
| `HGT` | m | Elevation (DEM) |
| `ASPECT` | degrees | Slope aspect |
| `SLOPE` | degrees | Terrain slope angle |
| `MASK` | boolean (0/1) | Glacier mask |

---

## Output Format — Result netCDF

Output is written to `data/output/<prefix>_<start>-<end>.nc` with dimensions `(time, lat, lon)`:

### Atmospheric variables (`output_atm`)
| Variable | Units | Description |
|----------|-------|-------------|
| `RAIN` | mm | Liquid precipitation per timestep |
| `SNOWFALL` | m w.e. | Solid precipitation per timestep |
| `LWin` | W m^-2 | Incoming longwave radiation |
| `LWout` | W m^-2 | Outgoing longwave radiation |
| `H` | W m^-2 | Sensible heat flux |
| `LE` | W m^-2 | Latent heat flux |
| `B` | W m^-2 | Ground heat flux |
| `QRR` | W m^-2 | Rain heat flux |
| `Z0` | m | Roughness length |
| `ALBEDO` | - | Surface albedo (0-1) |
| `TS` | K | Surface temperature |

### Internal variables (`output_internal`)
| Variable | Units | Description |
|----------|-------|-------------|
| `ME` | W m^-2 | Melt energy |
| `MB` | m w.e. | Total mass balance per timestep |
| `surfMB` | m w.e. | Surface mass balance per timestep |
| `intMB` | m w.e. | Internal mass balance per timestep |
| `EVAPORATION` | m w.e. | Evaporation per timestep |
| `SUBLIMATION` | m w.e. | Sublimation per timestep |
| `CONDENSATION` | m w.e. | Condensation per timestep |
| `DEPOSITION` | m w.e. | Deposition per timestep |
| `surfM` | m w.e. | Surface melt per timestep |
| `subM` | m w.e. | Subsurface melt per timestep |
| `Q` | m w.e. | Runoff per timestep |
| `REFREEZE` | m w.e. | Refreezing per timestep |
| `SNOWHEIGHT` | m | Total snow height |
| `TOTALHEIGHT` | m | Total column height (snow + ice) |
| `LAYERS` | count | Number of active layers |

### Full field variables (`output_full`, if `full_field = true`)
4D: `(time, lat, lon, layer)`
| Variable | Units | Description |
|----------|-------|-------------|
| `HEIGHT` | m | Layer heights |
| `RHO` | kg m^-3 | Layer densities |
| `T` | K | Layer temperatures |
| `LWC` | m w.e. | Layer liquid water content |
| `CC` | J m^-2 | Cold content |
| `POROSITY` | - | Layer porosity |
| `ICE_FRACTION` | - | Ice fraction |
| `IRREDUCIBLE_WATER` | - | Irreducible water content |
| `REFREEZE` | m w.e. | Layer refreeze amount |

---

## Unit Trap Table

These are the most dangerous unit conversion mistakes when preparing COSIPY inputs.

| # | Variable | COSIPY expects | Common source format | Conversion | Silent failure mode |
|---|----------|---------------|---------------------|------------|---------------------|
| 1 | T2 | K | degC (ERA5, AWS) | + 273.16 | Wrong snow/rain partition; all precip as rain |
| 2 | RH2 | % (0-100) | fraction (0-1) | * 100 | Near-zero latent heat; no sublimation |
| 3 | PRES | hPa | Pa (ERA5) | / 100 | Turbulent fluxes 100x too large |
| 4 | RRR | mm per timestep | mm/day, m/s | depends on dt | Precip 24x too high or too low |
| 5 | G | W m^-2 (instantaneous) | J m^-2 (accumulated, ERA5) | / dt_seconds | Radiation 3600x too high |
| 6 | SNOWFALL | m snow height | m w.e. or mm | / density * 1000 | Snow layer creation fails |
| 7 | N | fraction (0-1) | % (0-100) | / 100 | Longwave radiation > 500 W/m^2 |
| 8 | LWin | W m^-2 | J m^-2 (accumulated) | / dt_seconds | Longwave completely wrong |
| 9 | U2 | m s^-1 at 2m | m s^-1 at 10m (ERA5) | * log(2/z0)/log(10/z0) | Turbulent fluxes 30-50% too high |
| 10 | SLOPE | degrees | radians | * 180/pi | Radiation correction wrong |

---

## Configuration Reference

### config.toml — Key sections

| Section | Key | Default | Description |
|---------|-----|---------|-------------|
| SIMULATION_PERIOD | time_start | "2009-01-01T06:00" | ISO 8601 start |
| SIMULATION_PERIOD | time_end | "2009-01-10T00:00" | ISO 8601 end |
| FILENAMES | data_path | "./data/" | Base data directory |
| FILENAMES | input_netcdf | "Zhadang/..." | Relative path to forcing |
| FILENAMES | output_prefix | "Zhadang_ERA5" | Output file prefix |
| DIMENSIONS | WRF | false | Use WRF dimension names |
| PARALLELIZATION | workers | 0 (=all cores) | Dask workers count |
| FULL_FIELDS | full_field | false | Write layer-resolved output |

### constants.toml — Key sections

| Section | Key | Default | Units | Description |
|---------|-----|---------|-------|-------------|
| GENERAL | dt | 3600 | s | Time step (must match input) |
| GENERAL | max_layers | 200 | - | Max vertical layers |
| GENERAL | z | 2.0 | m | Measurement height |
| PARAMETERIZATIONS | albedo_method | Oerlemans98 | - | Albedo scheme |
| PARAMETERIZATIONS | stability_correction | Ri | - | Ri or MO |
| INITIAL_CONDITIONS | initial_snowheight_constant | 0.2 | m | Initial snow depth |
| INITIAL_CONDITIONS | initial_glacier_height | 40.0 | m | Glacier ice thickness |
| INITIAL_CONDITIONS | temperature_bottom | 270.16 | K | Bottom boundary T |
| CONSTANTS | albedo_fresh_snow | 0.85 | - | Fresh snow albedo |
| CONSTANTS | albedo_firn | 0.55 | - | Firn albedo |
| CONSTANTS | albedo_ice | 0.3 | - | Ice albedo |
| CONSTANTS | ice_density | 917.0 | kg m^-3 | Ice density |
| CONSTANTS | water_density | 1000.0 | kg m^-3 | Water density |
| CONSTANTS | zero_temperature | 273.16 | K | Melting point |

---

## Critical Domain Knowledge

### 1. Temperature must be in Kelvin (dt_001)
COSIPY expects T2 in Kelvin. AWS data often in degC. If temperature is in Celsius, the snow/rain partitioning function `tanh((T2 - 273.16 - center) * spread)` will treat all precipitation as rain (since T2 - 273.16 will be very negative like -293). No error message — just zero snowfall.

### 2. Pressure must be in hPa (dt_003)
COSIPY expects PRES in hPa (hectopascals). ERA5 provides Pa. Bounds check is 200-1080 hPa. If Pa values (e.g., 101325) are passed, the turbulent transfer coefficients will be wrong, producing unrealistic sensible/latent heat fluxes.

### 3. Total precipitation vs. Snowfall (dt_004)
COSIPY has two precipitation pathways:
- If both `RRR` and `SNOWFALL` are in the input: uses both directly (rain = RRR - SNOWFALL * density/1000)
- If only `RRR`: partitions into snow/rain using a tanh transfer function based on temperature
- If only `SNOWFALL`: uses snowfall directly, no rain
The `force_use_TP` flag forces use of RRR even if SNOWFALL is present.

### 4. Cloud cover N is a FRACTION (0-1), not percentage (dt_007)
Despite RH2 being in %, cloud cover N is expected as a fraction 0-1. If N>1, the longwave radiation parameterization will produce values > 500 W/m^2, causing unrealistic surface warming and extreme melt.

### 5. Time step dt must match input data frequency (dt_005)
The `dt` constant (default 3600s = 1 hour) must exactly match the temporal resolution of the input netCDF. Mismatch causes incorrect accumulation of snowfall, runoff, and all mass balance terms (they scale linearly with dt).

### 6. Initial conditions strongly affect spinup (dt_010)
Initial snowheight, glacier height, and temperature profile affect the first months of simulation. For production runs, use a restart file from a spinup period of at least 1 year with the same forcing.

---

## Entry Points (CLI commands after pip install)

| Command | Function |
|---------|----------|
| `cosipy-run` / `run-cosipy` | Main model execution |
| `cosipy-help` | Print help and CLI options |
| `cosipy-setup` | Generate template config files |
| `cosipy-aws2cosipy` | AWS CSV to COSIPY netCDF |
| `cosipy-wrf2cosipy` | WRF output to COSIPY netCDF |
| `cosipy-create-static` | Create static file from DEM |
| `cosipy-plot-field` | Plot spatial fields |
| `cosipy-plot-profile` | Plot vertical profiles |
| `cosipy-shortcuts` | List all entry points |

---

## Model Execution

```bash
# Default (uses config.toml, constants.toml in current directory)
python COSIPY.py

# Custom config paths
python COSIPY.py -c path/to/config.toml -x path/to/constants.toml

# With SLURM (set slurm_use=true in config.toml)
python COSIPY.py -s path/to/slurm_config.toml
```

### Runtime expectations
- Zhadang 1x1 grid, 10 days (240 hours): ~10 seconds
- Zhadang 7x13 grid, 1 year: ~5-15 minutes
- HEF multi-year distributed: hours (depends on grid size and workers)

---

## Physical Process Sequence (per timestep, per grid cell)

1. **Grid check**: Verify layer integrity
2. **Fresh snow density**: `max(109 + 6*(T2-273.16) + 26*sqrt(U2), 50)` kg/m^3
3. **Snow/rain partition**: Via tanh transfer function or direct SNOWFALL variable
4. **Add fresh snow layer**: If SNOWFALL > minimum_snowfall (0.001 m)
5. **Grid update**: Merge thin/similar layers (log_profile or adaptive_profile remeshing)
6. **Albedo update**: Oerlemans98 or Bougamont05
7. **Roughness update**: Moelg12
8. **Surface energy balance**: Solve for surface temperature (Newton/Secant method)
   - Net shortwave (G * (1 - albedo))
   - Penetrating radiation (Bintanja95)
   - Longwave in/out
   - Sensible heat (bulk aerodynamic with stability correction)
   - Latent heat (sublimation/evaporation)
   - Ground heat flux (subsurface temperature gradient)
   - Rain heat flux
9. **Surface mass fluxes**: Melt, sublimation, deposition, evaporation, condensation
10. **Melt removal**: Remove melted mass from grid
11. **Percolation**: Route liquid water through layers
12. **Refreezing**: Refreeze percolated water in cold layers
13. **Heat equation**: Solve subsurface temperature diffusion
14. **Densification**: Update layer densities (Boone/empirical/constant)
15. **Mass balance**: surface_MB + internal_MB = total_MB

---

## References

- Sauter, T., & Arndt, A. (2020). COSIPY v1.3 — An open-source coupled snowpack and ice surface energy and mass balance model. *Geoscientific Model Development*, 13, 5645-5662. doi:10.5194/gmd-13-5645-2020
- Oerlemans, J., & Knap, W. H. (1998). A 1 year record of global radiation and albedo in the ablation zone of Morteratschgletscher, Switzerland. *Journal of Glaciology*, 44(147), 231-238.
- Bougamont, M., et al. (2005). Sensitivity of ocean circulation to warming of the northeast Atlantic continental shelf. *Geophysical Research Letters*, 32.
- Moelg, T., et al. (2012). Quantifying climate change in the tropical midtroposphere over East Africa from glacier shrinkage on Kilimanjaro. *Journal of Climate*, 25(21), 7406-7414.
