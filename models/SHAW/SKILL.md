---
name: shaw
description: >-
  SHAW v3.03. Covers 1-D vertical coupled heat, water, and solute transfer through a
  single plant canopy - snow -…; Soil freezing/thawing: ice content, frost/thaw depth,
  freeze-thaw cycles with latent-heat coupling; Multi-layer snowpack: density/grain
  metamorphism, albedo decay, liquid retention and snowmelt; Explicit crop-residue
  heat/water/vapor transfer. Use when the task involves running, configuring, calibrating
  or interpreting SHAW.
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
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
>
> Before starting, run: `python preflight_check.py` (in this KI directory)

> **HWSD soil lookup:** Use `from ki_tools_common.soil_utils import lookup_hwsd` to get sand/silt/clay/OC/pH for any lat/lon. Returns texture class and Saxton-Rawls hydraulic properties.
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
SHAW forcing tool is in `s2_weather_prep/tools/` in this KI:
- `s2_weather_prep/tools/convert_forcing_to_shaw.py` — Converts CMFD/MSWX/NASA POWER to SHAW weather format (hourly or daily); handles specific humidity→RH, pressure Pa→kPa, solar radiation units

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/HWSD/SKILL.md` for soil property documentation.

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
The binary is ALREADY COMPILED at `KISSPATH_BINARIES/shaw/shaw303`
(a symlink to `model/shaw/Shaw303/shaw303`). To rebuild, use the shipped script
(handles gfortran 10+ legacy flags) — do NOT invent a `Code/` path, there is none:
```bash
cd KISSPATH_BINARIES/shaw
bash compile.sh    # gfortran -O2 -w -std=legacy -fallow-argument-mismatch
                   #   -o Shaw303/shaw303 Shaw303/Code+Debug/Shaw303.for
                   # + symlink model/shaw/shaw303
```

### Running
```bash
cd /path/to/input/files
KISSPATH_BINARIES/shaw/shaw303
# When prompted, enter: Trial.303.inp
```
SHAW reads from stdin — it prompts for the .inp file path AND a final
"Press Enter to end". For automation, pipe BOTH (triplet shaw_024):
```bash
printf "Trial.303.inp\n\n" | KISSPATH_BINARIES/shaw/shaw303
```
NOTE: SHAW normally exits with a benign Fortran EOF backtrace (non-zero return
code) when it reaches the end of the weather file, yet writes COMPLETE output.
Judge success by non-empty `.out` files, not by the return code (triplet shaw_018).

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

### ⚠️ Soil Node Column Format — IWRC=1 (Campbell) — ACTUAL .sit format

The actual binary format used by SHAW v3.03 for each soil node line is **12 columns**:

```
DEPTH  SAND  SILT  CLAY  OM  KSAT  BD  THETA_INIT  TINIT  BCAP  QUARTZ  BPAR
```

| Col | Name | Units | Notes |
|-----|------|-------|-------|
| 0 | DEPTH | m | Node depth (0.00 = surface) |
| 1 | SAND | % | Sand fraction (0–100) |
| 2 | SILT | % | Silt fraction |
| 3 | CLAY | % | Clay fraction |
| 4 | OM | % | Organic matter (OC × 1.724) |
| 5 | KSAT | cm/hr | Saturated hydraulic conductivity |
| 6 | BD | kg/m³ | Bulk density (written as `1360.`) |
| 7 | THETA_INIT | m³/m³ | Initial volumetric water content |
| 8 | TINIT | °C | Initial soil temperature |
| 9 | BCAP | m | Air-entry potential (negative, e.g. `-0.30`) |
| 10 | QUARTZ | 0–1 | **Thermal parameter** — quartz fraction of mineral particles (Johansen 1975) |
| 11 | BPAR | — | **Campbell's b** — pore-size distribution index (Rawls et al. 1982) |

> **WARNING — template trap**: The Compton Quebec template ships with `QUARTZ=8.5` and `BPAR=30.0` — both physically impossible or wrong. `QUARTZ` must be 0–1. `BPAR=30` means soil stays liquid to −150°C, disabling freeze-thaw simulation. ALWAYS apply pedotransfer corrections (see below).

### ⚠️ BPAR and QUARTZ — Pedotransfer Functions (CRITICAL for freeze-thaw)

**BPAR (Campbell's b)** controls both:
- Water retention curve shape: ψ = BCAP × (θ/θ_sat)^(−BPAR)
- Freeze-thaw: unfrozen water at temperature T < 0°C: θ_L/θ_sat = (6230/|BCAP|)^(−1/BPAR)

With BPAR=30: 72% liquid water at −15°C → soil never freezes. With BPAR=6–9 (correct for loam/clay): 5–20% liquid at −15°C → realistic freeze-thaw.

**Pedotransfer functions** (apply via `fix_bpar_quartz_from_texture()` in `setup_shaw_from_template.py`):

```python
# Rawls et al. (1982) — Campbell b from texture
bpar   = 3.10 + 0.157 * clay - 0.003 * sand     # typical NE China: 6–10
bpar   = max(2.0, min(12.0, bpar))               # clamped

# Johansen (1975) — quartz fraction from sand content  
quartz = min(0.85, max(0.10, sand/100.0 * 0.9 + 0.10))

# Cosby et al. (1984) — BCAP (air-entry, m, negative)
bcap   = -0.01 * (10.0 ** (1.54 - 0.0095*sand + 0.0063*(100-sand-clay)))
bcap   = max(bcap, -1.0)
bcap   = min(bcap, -0.05)
```

**Always call after template setup:**
```python
from models.SHAW.knowledge_infrastructure.tools.s1_site_setup.setup_shaw_from_template import fix_bpar_quartz_from_texture
n = fix_bpar_quartz_from_texture(sit_path)
```

Or from `run_shaw_parallel.py` — `fix_bpar_quartz_in_sit(sit_path)` is defined inline and called after every template setup.

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

---

## Validated: NE China Black Soil Domain — 6 Stations (2021–2022)

**Data source**: Black Soil Observation Data NE China V2.0 (32 AWS/soil stations)
- Local path: `data/china_data/BlackSoilObsData_NE_China_V2.0/ObservationData/`
- Sensor: combined AWS with TDR soil moisture + soil temperature at a single depth
- Format: xlsx, header at row 10, ~30-min records
- Column format varies by station (8–15 columns): use column index, not name matching

**6 validation cells and station mapping:**

| Cell label | Station name | Lat/Lon (sensor) | 0.25° cell | Data period | Depth |
|---|---|---|---|---|---|
| `47p3750_123p6250` | EcologicalQiqihar (Fulaerji) | 47.269°N, 123.686°E | 47.375°N, 123.625°E | May 2021–Dec 2022 | unknown (est. 5–10cm) |
| `47p8750_125p3750` | YianVegetables | 47.875°N, 125.375°E | same | May 2021–Dec 2022 | **20cm and 40cm** |
| `43p3750_124p3750` | LishuSiping | 43.375°N, 124.375°E | same | Jun–Nov 2022 | **20cm** (mulch + bare) |
| `47p3750_126p3750` | HailunSuihua | 47.254°N, 126.473°E | 47.375°N, 126.375°E | Jun–Dec 2022 | unknown (est. 5–10cm) |
| `44p6250_123p6250` | ChanglingSongyuan | 44.625°N, 123.625°E | same | Jun–Dec 2022 | unknown (est. 5–10cm) |
| `46p6250_131p6250` | YouyiShuangyashan | 46.625°N, 131.625°E | same | Jun–Dec 2022 | unknown (est. 5–10cm) |

**Observed monthly soil moisture (% VWC)** — EcologicalQiqihar (best station, 2 full years):

| Month | SM (%) | ST (°C) | Notes |
|-------|--------|---------|-------|
| May | 33–35 | 12–16 | Post-snowmelt refill |
| Jun | 37–38 | 20 | Peak growing season onset |
| Jul | 40–41 | 23–25 | Maximum moisture |
| Aug | 34–40 | 21–22 | Post-rain peak |
| Sep | 26–39 | 16–18 | Drainage |
| Oct | 27–35 | 6–8 | Pre-freeze drying |
| Nov | 21–29 | -1 | Onset of freezing |
| Dec | 13–17 | -5 to -9 | Partially frozen (liquid water) |
| Jan | ~13 | -9 | Deeply frozen |
| Feb | ~13 | -9 | Peak frozen |
| Mar | ~21 | -3 | Thaw begins |
| Apr | ~33 | 4 | Rapid thaw refill |

Growing season (May–Oct) mean: **35.5%**  |  Winter (Nov–Mar) mean: **18.2%** (liquid only)

**Literature reference (Chinese Geographical Science, Springer):**  
NE China Mollisol field capacity = 23.5–37% VWC, mean **31.65%** across 113 soil profiles.  
Winter liquid water (frozen Mollisol, 5–20cm): **0–10% VWC** in frozen layers [from-memory, unverified beyond search result].

**Key obs data notes:**
- EcologicalQiqihar is the only station with complete freeze-thaw cycle data (Qiqihar city, MWRC experimental base)
- YianVegetables and LishuSiping measure at 20–40cm — not directly comparable to SHAW 5cm node
- HailunSuihua, ChanglingSongyuan, YouyiShuangyashan show anomalously high SM (50–70%) starting Jun 2022 only — likely sensor calibration issue or near-saturated wetland soil; treat with caution
- Compare SHAW `liquid.out` (not `moist.out`) against these sensors — sensors detect liquid water only

**SHAW performance (6-cell HWSD-corrected run, `ne_china_shaw_hwsd/`):**
- Before BPAR fix (BPAR=30): Qiqihar SM PBIAS = +29.4% (soil never froze, liquid stayed at 35% while obs dropped to 13%)
- After BPAR fix (BPAR=6.92 from Rawls 1982): Qiqihar winter liquid drops to 11–17% — physically correct
- Growing season dry bias (PBIAS ≈ −24%): caused by HWSD bulk density overestimate (BD=1380 vs. ~1100 kg/m³ for NE China Mollisols)

**Run scripts:**
- 6-cell validation: `outputs/ne_china_shaw_vic_dssat/run_shaw_hwsd_validation.py`
- Full 2223-cell domain: `outputs/ne_china_shaw_vic_dssat/run_shaw_parallel.py` (includes `fix_bpar_quartz_in_sit()` as of 2026-05-13)
