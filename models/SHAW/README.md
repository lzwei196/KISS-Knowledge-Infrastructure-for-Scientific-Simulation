> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.

---

# SHAW Model (Simultaneous Heat and Water) v3.03 — Knowledge Infrastructure

## What is SHAW?

The **Simultaneous Heat and Water (SHAW)** model is a 1D field-scale model that simulates coupled heat, water, and solute transfer through a soil-plant-snow-residue-atmosphere system. Developed by Gerald N. Flerchinger at USDA-ARS Northwest Watershed Research Center (Boise, Idaho).

SHAW is one of the most detailed models available for:
- **Soil freezing and thawing** — detailed ice content profiles, frost depth, freeze-thaw cycles
- **Snowmelt** — multi-layer snowpack with grain metamorphism, density evolution, albedo decay
- **Crop residue layer** — explicit heat/water transfer through standing dead material and surface litter
- **Multi-species plant canopy** — stomatal resistance, transpiration, canopy energy balance
- **Solute transport** — up to 10 solute types with advection-dispersion

## SHAW vs RZ-SHAW (Why Standalone?)

| Feature | Standalone SHAW v3.03 | RZ-SHAW (embedded in RZWQM2) |
|---------|----------------------|------------------------------|
| Soil layers | Up to 50 nodes | Limited by RZWQM2 layering |
| Solute transport | Up to 10 solute types | Uses RZWQM2 chemistry instead |
| Snow layers | Multi-layer with metamorphism | Simplified |
| Residue layer | Full dynamics (changing cover, thickness) | Fixed within season |
| Lateral flow | Sub-surface lateral flow output | Not available |
| Water retention | Campbell, Brooks-Corey, or van Genuchten | Van Genuchten only |
| Plant canopy | Up to 10 canopy nodes, Stewart-Jarvis stomatal | Simplified |
| Soil source/sink | External water extraction/injection | Not available |
| CO2 simulation | v3.03-CO2 beta (GPP, NEE, Reco) | Not available |

The standalone version has **more physics options** and is required for detailed freeze-thaw studies, snow research, and CO2 flux simulation.

## Installation

### Requirements
- **Compiler**: gfortran (GNU Fortran) or any Fortran 77 compiler
- **No external dependencies** — pure Fortran 77, self-contained
- **OS**: Linux, macOS, Windows (with MinGW or Cygwin)

### Compilation
```bash
cd KISSPATH_BINARIES/shaw/Code
gfortran -O2 -o shaw303 shaw303.f
# Or if multiple source files:
# gfortran -O2 -o shaw303 *.f
```

### Running
```bash
cd /path/to/input/files
KISSPATH_BINARIES/shaw/Code/shaw303
# When prompted, enter: Trial.30.inp
```
SHAW reads from stdin — it prompts for the .inp file path. For automation, pipe it:
```bash
echo "Trial.30.inp" | KISSPATH_BINARIES/shaw/Code/shaw303
```

## Input Files (5 required + 3 optional)

### Required Files
| File | Extension | Purpose |
|------|-----------|---------|
| **Input/Output List** | `.inp` | Master control: version, timestep, flags, paths to all other files, output frequencies |
| **Site Characteristics** | `.sit` | Title, simulation dates, lat/lon/slope/aspect/elevation, soil layers, snow/residue/solute params |
| **Weather Data** | `.wea` | Hourly or daily meteorological forcing (T, wind, humidity, precip, snow density, solar radiation) |
| **Moisture Profile** | `.moi` | Initial soil moisture profiles (volumetric water content or matric potential) |
| **Temperature Profile** | `.tem` | Initial soil temperature profiles |

### Optional Files
| File | Purpose | When needed |
|------|---------|-------------|
| **Plant Growth** | Temporal LAI, height, biomass per species | MCANFLG=1 or 3 |
| **Surface Residue** | Changing residue cover, thickness, albedo | NRCHANG=1 |
| **Soil Source/Sink** | External water injection/extraction per layer | MWATRXT=1 |

## Weather File Format

### Hourly (MTSTEP=0):
```
JD  JH  JYR  TA  WIND  HUM  PRECIP  SNODEN  SUNHOR
```
- TA: Air temperature (C)
- WIND: Wind speed (m/s with IFLAGSI=1, else mph)
- HUM: Relative humidity (%)
- PRECIP: Precipitation (mm with IFLAGSI=1, else inches)
- SNODEN: New snow density (g/cm3, 0=auto-calculate)
- SUNHOR: Total solar radiation on horizontal surface (W/m2)

### Daily (MTSTEP=1):
```
JD  JYR  TMAX  TMIN  TDEW  WIND  PRECIP  SOLAR
```
- TMAX/TMIN: Max/min daily air temperature (C)
- TDEW: Dew-point temperature (C)
- WIND: Average wind speed (m/s with IFLAGSI=1, else miles/day)
- PRECIP: Daily precipitation (mm with IFLAGSI=1, else inches)
- SOLAR: Average daily solar radiation (W/m2)

### UNIT TRAPS (CRITICAL)
| Variable | SI (IFLAGSI=1) | English (IFLAGSI=0) | Common error |
|----------|---------------|---------------------|--------------|
| Wind speed | m/s | mph (hourly) or miles/day (daily) | CMFD/MSWX wind is m/s -- set IFLAGSI=1 |
| Precipitation | mm | inches | VIC precip is mm -- set IFLAGSI=1 |
| Solar radiation | W/m2 | W/m2 | Same in both -- no conversion needed |
| Soil Ksat | cm/hr | cm/hr | Always cm/hr regardless of IFLAGSI |
| Soil depth | m | m | Always meters |

## Site File Structure

The site file (.sit) has a complex multi-section structure:
- **Lines A-E**: General info (title, dates, location, materials, roughness)
- **Lines F**: Plant canopy parameters (if NPLANT > 0)
- **Line G**: Snow parameters
- **Line H**: Residue parameters (if NR > 0)
- **Lines I**: Solute parameters (if NSALT > 0)
- **Lines J**: Soil properties (boundary conditions, albedo, water retention curve, per-layer properties)

### Soil Water Retention Options (IWRC)
| IWRC | Equation | Parameters per layer |
|------|----------|---------------------|
| 1 | Campbell | psi_e, theta_s, b |
| 2 | Brooks-Corey | psi_e, theta_s, lambda, theta_r, l |
| 3 | Van Genuchten | theta_s, n, theta_r, l, alpha (set psi_e=0) |

## Output Files (up to 19)

| File | Content | Key variables |
|------|---------|--------------|
| OUT.out | General output | Daily/hourly summary |
| TEMP.out | Soil temperature profiles | T(z,t) at each node |
| MOIST.out | Total water content profiles | theta_total(z,t) |
| LIQUID.out | Liquid water content profiles | theta_liquid(z,t) |
| MATRIC.out | Matric potential profiles | psi(z,t) |
| ENERGY.out | Surface energy balance | Rn, H, LE, G |
| WATER.out | Water balance summary | Precip, ET, runoff, drainage |
| WFLOW.out | Vertical water flux between layers | q(z,t) |
| ROOTXT.out | Plant root water extraction | per layer per species |
| LATERAL.out | Sub-surface lateral flow | lateral q(z,t) |
| FROST.out | Frost/thaw/snow depth | frost_depth, thaw_depth, SWE |
| CANTMP.out | Canopy air temperature | T_canopy(z,t) |
| CANHUM.out | Canopy humidity | RH or vapor pressure |
| SNOWTMP.out | Snow layer temperatures | T_snow(z,t) |
| SALTS.out | Total salt concentration | C_total(z,t) |
| SOLUTE.out | Solution concentration | C_solution(z,t) |

## Pipeline (7 stages)

### s1_site_setup
Generate the `.sit` file from HWSD soil database + DEM slope/aspect + land cover.

### s2_weather_prep
Convert CMFD/MSWX/NASA POWER forcing to SHAW weather format.

### s3_plant_config
Configure plant canopy parameters from AVHRR land cover or DSSAT crop parameters.

### s4_initial_conditions
Generate initial soil moisture and temperature profiles from VIC output or climatology.

### s5_snow_residue_config
Configure snow parameters and crop residue layer properties.

### s6_execution
Run SHAW model, monitor progress, parse output files.

### s7_vic_coupling
Convert VIC grid cell parameters to SHAW format, run SHAW per cell for enhanced freeze-thaw.

## VIC Coupling Strategy

SHAW provides detailed freeze-thaw physics that VIC's simplified frost scheme cannot match.
The coupling approach:
1. Run VIC normally to get grid-cell water/energy balance
2. For cells where freeze-thaw is important (high latitude, high altitude):
   - Convert VIC soil parameters to SHAW format (via `vic_to_shaw_soil.py`)
   - Convert CMFD/MSWX forcing to SHAW weather format (via `convert_forcing_to_shaw.py`)
   - Initialize SHAW from VIC soil moisture/temperature
   - Run SHAW per cell for detailed frost depth, ice content, freeze-thaw timing
3. Use SHAW output to correct VIC's infiltration/runoff during frozen soil periods

## Fortran 77 Traps (from PREFLIGHT)

| Trap | SHAW-specific notes |
|------|-------------------|
| **Path length limit** | 80 characters max for all file paths in .inp file |
| **Free format input** | All SHAW input files use free format (blank/comma separated) -- NOT fixed-width columns |
| **STOP on error** | SHAW may STOP with no error message -- check output files exist |
| **99999 sentinel** | Temperature value 99999 in .tem file means "no measurement" -- model interpolates |
| **File path case** | Linux is case-sensitive -- use exact case for file names |
| **Fortran I/O units** | SHAW uses many I/O units (10-40+) -- may conflict with system limits |

## Key References

- Flerchinger, G.N. (2017). The Simultaneous Heat and Water (SHAW) Model: User's Manual Version 3.0.x. Technical Report NWRC 2017-01.2.
- Flerchinger, G.N., Saxton, K.E. (1989). Simultaneous heat and water model of a freezing snow-residue-soil system. Trans. ASAE, 32(2):565-571.
- Flerchinger, G.N., Pierson, F.B. (1991). Modeling plant canopy effects on variability of soil temperature and water. Agric. For. Meteorol., 56:227-246.

---

## Validated: JackPine Boreal Forest (OJP BERMS), Saskatchewan, Canada

**Data source**: BERMS (Boreal Ecosystem Research and Monitoring Sites)
- Operated by Environment and Climate Change Canada (ECCC)
- Site: Old Jack Pine (OJP), ~53.916°N, 104.692°W, 580m elevation
- Part of FLUXNET / AmeriFlux network
- Local path: `KISSPATH_DATA/observedST-SM/soil_temperatureand_soil_moisture_canada/sas_forest/`
- Reference: Barr et al. (2012) JGR-Biogeosciences; Zha et al. (2010) Global Change Biology

**Data used**:
- `JackPine_Met.csv` — 30-min: T, P, SWi, RH, WS, LWi (1998-2016)
- `JackPine_Soil.csv` — 30-min: VWC (5 depths) + ST (6 depths: 2,5,10,20,50,100 cm)
- `JackPine_Snow.csv` — 30-min: SnowT, SD_Clearing, SD_BlwCanopy

**Simulation**: 1999, hourly timestep, 365 days, ~30 seconds runtime

### Soil Temperature Performance (uncalibrated)

| Depth | RMSE (°C) | Bias (°C) | R² |
|-------|----------|----------|-----|
| 2 cm | 4.32 | +0.01 | 0.921 |
| 5 cm | 4.32 | +0.05 | 0.910 |
| 10 cm | 3.95 | +0.16 | 0.914 |
| 20 cm | 3.33 | +0.25 | 0.921 |
| 50 cm | 1.45 | +0.19 | 0.955 |
| 100 cm | 1.83 | +0.31 | 0.913 |

### Water Balance
- Annual P: 466 mm (literature ~430 mm)
- ET: 499 mm
- Snowmelt: 47 mm

### Input Format Issues Found (3 triplets)
- dt_v003: MCANFLG=0 must NOT have root distribution line
- dt_v004: NSALT=0 must NOT have ASALT/DISPER columns
- dt_v005: Weather file needs +24h padding for EOF avoidance

### Output files
All at `outputs/shaw_jackpine/`: 6 validation plots + SHAW input/output files

---

## Validated: Manitoba Station 544 (Alexander Prairie), Canada

**Data source**: Manitoba Agriculture Weather Program (MAWP)
- Station 544, Alexander, Manitoba (49.81°N, 100.37°W, 460m elevation)
- Prairie grassland (no canopy, MCANFLG=0)
- Local path: `KISSPATH_DATA/observedST-SM/soil_temperatureand_soil_moisture_canada/manitoba/`
- Soil temperature at 4 depths: 5, 20, 50, 100 cm

**Simulation**: Nov 2019 – Oct 2020, **daily weather input (MTSTEP=1)**, 364 days

### Soil Temperature Performance (uncalibrated)

| Depth | RMSE (°C) | Bias (°C) | R² |
|-------|----------|----------|-----|
| 5 cm | 6.17 | -2.54 | 0.895 |
| 20 cm | 5.00 | -1.81 | 0.894 |
| 50 cm | 3.89 | -0.70 | 0.821 |
| 100 cm | 2.93 | -2.09 | 0.778 |

### Frost & Snow
- Max frost depth: 25.1 cm (realistic for thin snowpack)
- Max snow depth: 11.8 cm, SWE: 11.8 mm (low — station precip gauge undercounts snow)
- Cold bias (-2 to -3°C) caused by insufficient snow insulation

### Water Balance
- Annual ET: ~208 mm (expected ~350 mm — low due to precip undercatch)
- Freeze-thaw cycle captured: soil freezes Nov-Mar, thaws by April

### Errors Found During Validation (6 triplets: shaw_026-031)

| # | Error | Impact | Fix |
|---|-------|--------|-----|
| shaw_026 | MTSTEP=0 but daily data | Zero precip read | Set MTSTEP=1 for daily |
| shaw_027 | Weather columns YR DOY instead of DOY YR | Wrong dates | Swap columns 1-2 |
| shaw_028 | Solar noon HRNOON=0.01 (should be 12.3) | Precip assigned to hour 0 | Compute from longitude |
| shaw_029 | Solar radiation MJ/m²/day not converted to W/m² | 11.6x too low energy | Multiply by 11.574 |
| shaw_030 | JSTART = first .wea DOY (needs +1) | No previous-day data | JSTART = first_wea_doy + 1 |
| shaw_031 | .sit generated from scratch, not from template | Multiple format errors | Use setup_shaw_from_template.py |

### Key Lesson: Daily vs Hourly Weather

SHAW supports BOTH formats via the MTSTEP flag in .inp Line B:

| MTSTEP | Format | Columns | Use when |
|--------|--------|---------|----------|
| 0 | Hourly | JD JH JYR TA WIND HUM PRECIP SNODEN SUNHOR (9 cols) | BERMS, FLUXNET, NASA POWER hourly |
| 1 | **Daily** | JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR (8 cols) | Manitoba MAWP, CMFD/MSWX aggregated, Environment Canada |
| 2 | Custom | Same as hourly, at NHRPDT intervals | Custom interval data |

**CRITICAL**: The daily format has NO hour column and uses TMAX/TMIN (not instantaneous TA). SOLAR is average daily W/m² (not instantaneous). Always verify column count matches MTSTEP.

### Output files
All at `outputs/shaw_manitoba_544/`: validation_soil_temp.png, validation_frost_snow.png
