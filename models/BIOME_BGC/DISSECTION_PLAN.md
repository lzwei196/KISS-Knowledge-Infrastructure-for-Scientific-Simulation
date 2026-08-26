# BIOME-BGC Knowledge Dissection Plan

> **Model**: BIOME-BGC 4.2 (University of Montana NTSG)
> **Domain**: Terrestrial biogeochemistry — daily C/N/water cycling for natural ecosystems (forests, grasslands, shrublands)
> **Language**: C (ANSI C, single-threaded, point-based)
> **License**: Public domain (developed under NASA/USGS funding)
> **Key publication**: Thornton et al. (2002), "Modeling and measuring the effects of disturbance history and climate on carbon and water budgets in evergreen needleleaf forests", Agricultural and Forest Meteorology 113:185-222
> **Planned KI package**: ~20 tools, ~10 skill documents, ~25 diagnostic triplets

---

## 1. Model Overview

### 1.1 What BIOME-BGC Is

BIOME-BGC (BioGeochemical Cycles) is a point-based, daily-timestep model that simulates carbon, nitrogen, and water fluxes through terrestrial ecosystems. Developed at the Numerical Terradynamic Simulation Group (NTSG), University of Montana by Peter Thornton, Steve Running, and colleagues. It is the scientific descendant of FOREST-BGC (Running & Coughlan 1988) and BIOME-BGC v4.1.1/4.2 (Thornton et al. 2002).

**Core processes simulated**:
- Photosynthesis (Farquhar model for C3, collatz for C4 — via stomatal conductance × CO2 gradient)
- Autotrophic respiration (maintenance + growth)
- Heterotrophic respiration (litter and soil organic matter decomposition, 4 litter + 4 SOM pools based on CENTURY model)
- Allocation of assimilated C to leaf, stem, root, and coarse woody debris pools
- Nitrogen mineralization, immobilization, nitrification, denitrification (simplified)
- Evapotranspiration (Penman-Monteith), soil evaporation, canopy interception
- Snowpack accumulation and melt
- Soil water balance (single bucket or multi-layer)
- Phenology (deciduous leaf onset/offset based on soil temperature and day length)
- Mortality and fire (disturbance parameters)

**What makes it unique for HydroCraft**:
- **Natural ecosystems**: Forests (evergreen needleleaf, evergreen broadleaf, deciduous needleleaf, deciduous broadleaf), grasslands (C3 and C4), shrublands. LDNDC focuses on cropland; BIOME-BGC fills the forest/grassland gap.
- **Full C cycle**: GPP, NPP, NEP, NEE, ecosystem respiration, C stock changes — the metrics used in IPCC carbon budgets and FLUXNET validation.
- **Spinup capability**: Runs to steady-state (hundreds to thousands of years) to initialize soil C/N pools. This is critical for realistic carbon flux estimates.
- **FLUXNET-compatible**: Outputs daily GPP, NEE, ET, sensible heat — directly comparable to eddy covariance measurements.
- **Minimalist input requirements**: One meteorological station + ecophysiology parameters + site description. No spatial data needed per se (point model), but can be run cell-by-cell across a VIC grid.

### 1.2 Version History and Source Code

| Version | Date | Key Changes | Source |
|---------|------|-------------|--------|
| FOREST-BGC | 1988 | Original forest model (Running & Coughlan) | — |
| BIOME-BGC 4.1.1 | ~2000 | Multi-biome, N cycle, C3/C4 photosynthesis | NTSG website |
| BIOME-BGC 4.2 | 2010 | Bug fixes, improved soil water, updated allocation | NTSG website (`bgc-4.2.tar.gz`) |
| BIOME-BGCMuSo | 2014+ | Hungarian extension: multi-layer soil, management, crop module | [GitHub: balazsz/bbgc_MuSo](https://github.com/balazsz/bbgc_MuSo) |
| Biome-BGCMuSo v6.2 | 2022+ | Multilayer soil (10 layers), soil moisture profile, harvest, thinning | GitHub |

**Recommended version for HydroCraft**: Start with **BIOME-BGC 4.2** (stable, simple, well-documented). Consider upgrading to **BIOME-BGCMuSo** later if multi-layer soil coupling with VIC is needed.

**Source code**:
- BIOME-BGC 4.2: `https://www.ntsg.umt.edu/project/biome-bgc.php` → Download `bgc-4.2.tar.gz`
- BIOME-BGCMuSo: `https://github.com/balazsz/bbgc_MuSo`

### 1.3 What BIOME-BGC Adds Beyond LDNDC

| Capability | LDNDC | BIOME-BGC | Significance |
|-----------|-------|-----------|-------------|
| **Forest C cycling** | Basic (PlaMox module, limited calibration for forests) | Core strength — designed for forests | Forest carbon budgets for IPCC reporting |
| **Natural grasslands** | Crop-focused management events | Native C3/C4 grassland ecophysiology | Rangeland/steppe carbon monitoring |
| **Spinup to steady-state** | No explicit spinup protocol | Built-in spinup mode (run until SOC equilibrium) | Realistic initial soil C/N pools |
| **GPP/NEE output** | Has GPP but not standard NEE | Standard NEE = NEP - disturbance | Direct FLUXNET validation |
| **Deciduous phenology** | Fixed management dates | Dynamic onset/offset from soil T + day length | Climate-sensitive leaf phenology |
| **CENTURY-style SOM** | DNDC SOM model (3 pools) | CENTURY SOM (4 litter + 4 SOM pools) | Industry-standard decomposition |
| **Agricultural systems** | Full management: tillage, fertilizer, irrigation, crop rotation | None (natural ecosystems only) | Complementary domains |
| **CH4 / N2O detail** | Detailed nitrification/denitrification, methanogenesis | Simplified N gas loss | LDNDC better for GHG hotspots |

**Key insight**: BIOME-BGC and LDNDC are **complementary, not competing**. Use LDNDC for cropland/managed systems GHG budgets; use BIOME-BGC for forest/grassland carbon cycling. At the ag-forest boundary (e.g., afforestation scenarios, forest-farmland mosaics), both models run on their respective land cover types within the same VIC grid.

### 1.4 BIOME-BGC vs CENTURY Comparison

| Feature | BIOME-BGC | CENTURY/DayCent |
|---------|-----------|-----------------|
| Timestep | Daily | Monthly (CENTURY) / Daily (DayCent) |
| Photosynthesis | Mechanistic Farquhar model | Empirical production function |
| Canopy radiation | Multi-layer, sunlit/shaded | Simple light-use efficiency |
| Soil C pools | 4 litter + 4 SOM (CENTURY-derived) | 3 litter + 3 SOM (original) |
| Water | Penman-Monteith ET, bucket soil water | Empirical PET, multi-layer soil water |
| N cycle | Mineralization, immobilization, simplified gaseous loss | Full N cycle including trace gas |
| Strengths | Forest physiology, mechanistic C | Grassland, management, N2O/CH4 |

---

## 2. Installation Plan

### 2.1 Compilation from Source

BIOME-BGC 4.2 is pure ANSI C with **no external library dependencies** — the simplest model to compile in the HydroCraft portfolio.

**Build steps** (estimated 2 minutes):
```bash
# Download source
wget https://www.ntsg.umt.edu/files/biome-bgc/bgc-4.2.tar.gz
tar -xzf bgc-4.2.tar.gz
cd bgc-4.2/

# Examine Makefile
cat Makefile
# Expected: simple gcc compilation with -O2 optimization

# Compile
make
# Produces: bgc (single executable)

# Verify
./bgc
# Should print usage message
```

**Expected structure of source tarball**:
```
bgc-4.2/
  src/           # C source files (~20 .c files, ~15,000 lines total)
    bgc.c        # Main driver
    met_init.c   # Meteorological data initialization
    epc_init.c   # Ecophysiological constants initialization
    sitec_init.c # Site constants initialization
    spinup_bgc.c # Spinup mode driver
    pointbgc.c   # Main simulation loop
    photosynthesis.c
    decomp.c     # Decomposition (CENTURY-style)
    phenology.c
    soilpsi.c    # Soil water potential
    ...
  inc/           # Header files
    bgc_struct.h # Data structures
    bgc_constants.h # Physical constants
    bgc_func.h   # Function prototypes
    ...
  ini/           # Example initialization files
    enf_temperate.ini  # Temperate evergreen needleleaf forest
    dbf_temperate.ini  # Temperate deciduous broadleaf forest
    c3grass.ini        # C3 grassland
    shrub.ini          # Shrubland
    ...
  epc/           # Ecophysiology parameter files
    enf_temperate.epc  # Parameter set for temperate ENF
    dbf_temperate.epc  # Parameter set for temperate DBF
    ...
  met/           # Example meteorological files
    daymet_example.mtc43  # Example met input
  Makefile
  README
```

**Dependencies**: None beyond standard C library (libc). GCC 4.x+ works. No MPI, no NetCDF, no HDF5, no LAPACK.

**Installation target**: `KISSPATH_BINARIES/biome-bgc/bgc-4.2/`
**Binary path**: `KISSPATH_BINARIES/biome-bgc/bgc-4.2/bgc`

### 2.2 Preflight Classification

Per PREFLIGHT.md, BIOME-BGC classifies as:

- [x] **Has C code** -> Check for fixed-width input parsing, hardcoded path lengths
- [x] **Reads fixed-width text files** -> .ini and .epc files have position-sensitive parsing
- [x] **Will be coupled with other models** -> VIC soil moisture, CMFD/MSWX met, MODIS GPP
- [x] **Has physical units** -> kgC/m2, kgN/m2, W/m2, Pa, etc.
- [ ] Uses spatial data -> Point model, no shapefiles (gridded runs handled externally)
- [x] **Is an ecosystem model** -> Forest/grassland phenology, allocation strategies
- [ ] Is a lake/reservoir model -> No
- [ ] Is a 2D flood model -> No
- [x] **Has a config file** -> .ini file controls everything

**Top trap risks**:
1. **Unit traps**: Met input units (shortwave in W/m2 vs kJ/m2/day, temperature C vs K, VPD in Pa vs kPa, precipitation in cm vs mm)
2. **Config file traps**: The .ini file has very specific line-by-line parsing — each line number corresponds to a specific parameter. Off-by-one = wrong parameter silently read.
3. **Coupling traps**: Double-counting ET (VIC + BIOME-BGC both compute ET), inconsistent soil water between models

---

## 3. Pipeline Stages

### Stage Overview Diagram

```
S1 (Site Definition) ─────────────────────────────────────┐
S2 (Ecophysiology Params) ────────────────────────────────┤
S3 (Meteorological Forcing) ──────────────────────────────┤
S4 (CO2 Concentration) ──────────────────────────────────┤
                                                           ▼
S5 (Spinup Execution) ─── centuries of cycling ──> S6 (Normal Execution)
                                                           │
                                                           ▼
S7 (Output Parsing & Flux Analysis) ──> S8 (FLUXNET Validation)
                                                           │
                                                           ▼
S9 (VIC/HydroCraft Coupling) ──> S10 (LDNDC Boundary Coupling)
```

### S1: Site Definition (.ini file)

**Purpose**: Define site physical characteristics — latitude, elevation, soil depth, soil texture, atmospheric N deposition, site-specific initial conditions.

**Knowledge type**: Evaluative (soil depth choice, sand/clay fractions from HWSD) + Procedural (INI file generation)

**Key inputs**:
- Latitude, longitude, elevation (from DEM or VIC grid)
- Soil depth (effective rooting depth, typically 1-2m)
- Soil texture: sand%, silt%, clay% (from HWSD via `hwsd_soil_adapter.py`)
- N deposition rate (kgN/m2/yr — from global datasets or LDNDC airchemistry)
- Initial conditions: soil water, snowpack (from VIC if coupled)

**INI file format** (critical — line-number-based parsing):
```
BIOME-BGC v4.2 initialization file
<met_file_path>                    (line 3: path to meteorological input)
<out_prefix>                       (line 4: output file prefix)
1                                  (line 5: 1=normal mode, 0=spinup mode)
0                                  (line 6: 1=read restart, 0=don't)
<restart_input>                    (line 7: restart input file path)
1                                  (line 8: 1=write restart, 0=don't)
<restart_output>                   (line 9: restart output file path)
2000                               (line 10: simulation start year)
365                                (line 11: number of meteorological years)
1                                  (line 12: 1=annual output, 0=no)
1                                  (line 13: 1=daily output, 0=no)
<epc_file_path>                    (line 14: ecophysiology parameter file)
45.5                               (line 15: site latitude in degrees)
0.0005                             (line 16: site N deposition, kgN/m2/yr)
0.0                                (line 17: site N fixation, kgN/m2/yr)
1.0                                (line 18: soil depth, meters)
54.0                               (line 19: sand percentage)
16.0                               (line 20: silt percentage)
30.0                               (line 21: clay percentage)
1000.0                             (line 22: site elevation, meters)
0.2                                (line 23: site shortwave albedo)
0.0001                             (line 24: atmospheric CO2 ppm / 1e6 OR constant)
0.0                                (line 25: initial snowwater, kgH2O/m2)
0.5                                (line 26: initial soil water as proportion of saturation)
```

**CRITICAL**: The .ini file is parsed **line by line** with no field names. If a line is missing or extra, every subsequent parameter is read into the wrong variable. This is the #1 anticipated silent error.

**Tools to build**:
- `generate_ini_file.py` — Generate .ini from structured inputs (lat, lon, soil, etc.)
- `hwsd_to_bgc_site.py` — Extract HWSD soil properties for a grid cell, convert to BIOME-BGC format

### S2: Ecophysiology Parameters (.epc file)

**Purpose**: Define plant functional type (PFT) parameters — photosynthetic capacity, allocation ratios, turnover rates, litter quality, phenology thresholds.

**Knowledge type**: Evaluative (PFT selection based on land cover) + Procedural (EPC file generation)

**The .epc file** contains ~40-50 parameters organized by category:
- Turnover fractions (leaf, fine root, live wood)
- Allocation ratios (new fine root C : new leaf C, new stem C : new leaf C, etc.)
- C:N ratios (leaf, leaf litter, fine root, live wood, dead wood)
- Canopy parameters (SLA, LAI_all:LAI_proj, canopy light extinction)
- Photosynthesis parameters (Vcmax, Jmax at 25C, quantum yield)
- Conductance parameters (cuticular, maximum stomatal, boundary layer)
- Litter and decomposition parameters (labile/cellulose/lignin fractions)
- Phenology controls (for deciduous: soil T onset, day length offset)
- Mortality and fire parameters

**Default PFT parameter sets** (bundled with BIOME-BGC):

| PFT Code | Ecosystem | Key Params (SLA, C:N_leaf, allocation) |
|----------|-----------|---------------------------------------|
| ENF | Evergreen needleleaf forest | SLA=8, C:N=42, high wood allocation |
| EBF | Evergreen broadleaf forest | SLA=12, C:N=30, high LAI |
| DNF | Deciduous needleleaf forest | SLA=15, C:N=25, larch phenology |
| DBF | Deciduous broadleaf forest | SLA=32, C:N=25, temperate deciduous |
| SHRUB | Shrubland | SLA=15, C:N=30, low stature |
| C3GRASS | C3 grassland | SLA=32, C:N=25, annual turnover |
| C4GRASS | C4 grassland | SLA=25, C:N=30, high WUE |

**Tools to build**:
- `generate_epc_file.py` — Generate .epc from PFT type + optional overrides
- `map_landcover_to_pft.py` — Map AVHRR (or MODIS) land cover classes to BIOME-BGC PFTs

**Mapping AVHRR land cover to BIOME-BGC PFTs**:

| AVHRR Class | Description | BIOME-BGC PFT |
|------------|-------------|---------------|
| 1 | Evergreen Needleleaf Forest | ENF |
| 2 | Evergreen Broadleaf Forest | EBF |
| 3 | Deciduous Needleleaf Forest | DNF |
| 4 | Deciduous Broadleaf Forest | DBF |
| 5 | Mixed Forest | DBF (dominant) or ENF (by latitude) |
| 6 | Woodland | SHRUB or DBF |
| 7 | Wooded Grassland | C3GRASS + SHRUB |
| 8 | Closed Shrubland | SHRUB |
| 9 | Open Shrubland | SHRUB |
| 10 | Grassland | C3GRASS (>40N) or C4GRASS (<30N) |
| 11 | Cropland | Skip (use LDNDC/DSSAT) |
| 12 | Bare Ground | Skip |
| 13 | Urban | Skip |

### S3: Meteorological Forcing (.mtcNN file)

**Purpose**: Prepare daily meteorological input — the primary driver of ecosystem fluxes.

**Knowledge type**: Procedural (format conversion, unit conversion) + Evaluative (quality checks)

**BIOME-BGC meteorological input format** (space-separated, no header, one line per day):

```
<year> <yday> <Tmax_C> <Tmin_C> <Tday_C> <prcp_cm> <VPD_Pa> <srad_W/m2> <daylen_s>
```

| Column | Variable | Unit | Source in CMFD/MSWX |
|--------|----------|------|---------------------|
| 1 | Year | integer | From date |
| 2 | Year-day | 1-365/366 | From date |
| 3 | Tmax | degrees C | Daily max of 3-hourly temperature (K -> C) |
| 4 | Tmin | degrees C | Daily min of 3-hourly temperature (K -> C) |
| 5 | Tday | degrees C | Daytime average temperature |
| 6 | Precipitation | **cm/day** | mm/day / 10 (CRITICAL: cm not mm!) |
| 7 | VPD | Pa | Compute from specific humidity + temperature |
| 8 | Shortwave radiation | W/m2 | Daily mean shortwave (already W/m2 in CMFD) |
| 9 | Day length | seconds | Computed from latitude + day of year |

**CRITICAL UNIT TRAPS**:
1. **Precipitation in cm, NOT mm**: BIOME-BGC expects cm/day. CMFD/MSWX provide mm. Forgetting to divide by 10 gives 10x precipitation — model runs fine, but GPP/NPP will be inflated and water balance wrong.
2. **VPD in Pa, NOT kPa**: Vapor pressure deficit must be in Pascals. Providing kPa gives 1000x too low VPD, causing stomata to stay fully open (unrealistic transpiration).
3. **Day length in seconds**: Must be computed from latitude and Julian day using astronomical formulas. Not available from CMFD/MSWX.
4. **Tday (daytime average)**: Not simply (Tmax+Tmin)/2. Should be the average temperature during daylight hours. Can approximate as Tmin + 0.45*(Tmax-Tmin) per Thornton & Running (1999).

**Tools to build**:
- `convert_cmfd_to_bgc_met.py` — CMFD 3-hourly -> BIOME-BGC daily met file
- `convert_mswx_to_bgc_met.py` — MSWX 3-hourly -> BIOME-BGC daily met file
- `convert_vic_forcing_to_bgc_met.py` — VIC forcing (7-col ASCII) -> BIOME-BGC met
- `compute_daylength.py` — Astronomical day length from latitude + DOY
- `compute_vpd.py` — VPD from temperature + humidity (specific or relative)

### S4: CO2 Concentration

**Purpose**: Provide atmospheric CO2 concentration for photosynthesis calculations.

**Knowledge type**: Procedural (simple data lookup/interpolation)

BIOME-BGC can use either:
1. A fixed CO2 concentration (set in .ini file, e.g., 380 ppm for year 2000)
2. A time-varying CO2 file (annual values, for transient simulations)

**For HydroCraft**:
- Historical simulations: Use Mauna Loa / NOAA ESRL annual CO2 (1959-present)
- CMIP6 projections: Use SSP-specific CO2 pathways
- Spinup: Use pre-industrial CO2 (280 ppm) for spinup, then ramp up

**Tools to build**:
- `generate_co2_file.py` — Generate annual CO2 from lookup table (year -> ppm)
- Reuse `generate_airchemistry_file.py` from LDNDC (shares CO2 data source)

### S5: Spinup Execution (CRITICAL — unique to BIOME-BGC)

**Purpose**: Run the model for hundreds/thousands of simulated years to bring soil carbon and nitrogen pools to steady-state equilibrium.

**Knowledge type**: Evaluative (convergence criteria, spinup strategy) + Procedural (restart file management)

**Why spinup is critical**:
- Soil organic carbon pools have turnover times of decades to millennia
- Starting from arbitrary initial conditions produces transient C fluxes for centuries
- Without proper spinup, NEE estimates are meaningless (dominated by initial condition artifacts)
- A typical spinup runs 1000-6000 simulated years (but takes only minutes of wall time because it's a point model)

**Spinup strategy**:

1. **Phase 1: Meteorological spinup** (optional, 100 years)
   - Cycle the available met data (e.g., 20 years of CMFD looped 5 times)
   - Establishes reasonable LAI, biomass

2. **Phase 2: Soil C/N equilibrium spinup** (1000-6000 years)
   - Run BIOME-BGC in spinup mode (`mode=0` in .ini)
   - Model recycles met data automatically
   - Continue until soil C pool changes < threshold (e.g., delta_SOC < 0.5 gC/m2/yr)
   - Write restart file at end

3. **Phase 3: Normal run** (actual simulation period)
   - Read restart file from spinup
   - Run with transient CO2, actual met data
   - This is the production simulation

**Convergence criteria** (from literature):
- Total ecosystem C change < 0.5 gC/m2/yr for 50 consecutive years
- Or: net N mineralization change < 0.01 gN/m2/yr
- Or: simpler — run for a fixed duration appropriate to biome:
  - Grassland: 1000-1500 years (fast turnover)
  - Deciduous forest: 2000-3000 years (moderate)
  - Evergreen forest: 3000-6000 years (slow)
  - Boreal forest: 4000-6000 years (very slow)

**Spinup acceleration** (Thornton & Rosenbloom 2005):
- After ~300 years, accelerate slow SOM pools by multiplying decomposition rates
- Reduces spinup time from 6000 to ~500 years
- BIOME-BGC 4.2 has this built in (check source for `SPINUP_ACCELERATION` flag)

**Tools to build**:
- `run_spinup.py` — Execute spinup with convergence monitoring
- `check_spinup_convergence.py` — Analyze spinup output for steady-state
- `manage_restart_files.py` — Handle restart file I/O between spinup and normal runs

**Skill document emphasis**: This stage needs the most detailed skill document in the entire BIOME-BGC KI. The spinup strategy depends on the biome, climate zone, and whether acceleration is used. Poor spinup is the #1 reason for unrealistic NEE in published studies.

### S6: Normal Execution

**Purpose**: Run the main BIOME-BGC simulation for the target period.

**Knowledge type**: Procedural (execution) + Evaluative (runtime checks)

**Command**:
```bash
./bgc <ini_file>
```

BIOME-BGC reads the .ini file, which points to all other inputs (.epc, .met, restart file). Output is written to files based on the prefix specified in .ini.

**Runtime**: Very fast — a point model running 10 years takes ~1 second. A gridded run of 100 cells x 10 years takes ~2 minutes. The bottleneck is I/O and spinup, not computation.

**Expected output files** (daily and/or annual, depending on .ini flags):
- `<prefix>.dayout` — Daily output (GPP, NPP, NEE, ET, soil water, LAI, etc.)
- `<prefix>.annout` — Annual summary
- `<prefix>.endpoint` — Restart file (state at end of simulation)

**Tools to build**:
- `run_bgc.py` — Execute BIOME-BGC with error handling, timeout, exit code check
- `run_bgc_grid.py` — Loop over VIC grid cells, run BIOME-BGC for each cell

### S7: Output Parsing and Flux Analysis

**Purpose**: Parse BIOME-BGC output files, compute derived quantities, format for analysis.

**Knowledge type**: Procedural (parsing) + Evaluative (physical reasonableness checks)

**Daily output columns** (typical for BIOME-BGC 4.2):
```
year yday GPP NPP NEE ET soilw snoww LAI vegc soilc litc cwdc npp_to_cpool
```

| Variable | Unit | Typical range (temperate forest) | Notes |
|----------|------|----------------------------------|-------|
| GPP | kgC/m2/day | 0-0.015 (peak summer) | Gross primary production |
| NPP | kgC/m2/day | 0-0.008 | Net primary production |
| NEE | kgC/m2/day | -0.008 to +0.005 | Net ecosystem exchange (negative = sink) |
| ET | kgH2O/m2/day (= mm/day) | 0-6 | Evapotranspiration |
| soilw | kgH2O/m2 | 50-500 | Soil water content |
| snoww | kgH2O/m2 | 0-500 | Snow water equivalent |
| LAI | m2/m2 | 0-8 | Leaf area index |
| vegc | kgC/m2 | 5-25 (forests) | Vegetation carbon stock |
| soilc | kgC/m2 | 5-20 | Soil organic carbon stock |
| litc | kgC/m2 | 0.1-1.0 | Litter carbon |
| cwdc | kgC/m2 | 0-5 | Coarse woody debris carbon |

**Derived quantities**:
- Annual GPP, NPP, NEE (sum daily values)
- Ecosystem respiration: Reco = GPP - NEE (when NEE convention is atmosphere-positive)
- Carbon Use Efficiency: CUE = NPP/GPP (~0.4-0.6)
- Water Use Efficiency: WUE = GPP/ET (gC/kgH2O, ~2-6 for forests)
- Growing season length: number of days with GPP > threshold

**Tools to build**:
- `parse_daily_output.py` — Read daily output, produce pandas DataFrame / CSV
- `parse_annual_output.py` — Read annual output
- `compute_carbon_budget.py` — Annual C budget with mass balance check
- `compute_flux_statistics.py` — Seasonal patterns, interannual variability, WUE/CUE

### S8: FLUXNET Validation

**Purpose**: Compare BIOME-BGC outputs against eddy covariance flux tower measurements.

**Knowledge type**: Evaluative (site selection, metric interpretation) + Procedural (data processing)

**FLUXNET data sources**:
- FLUXNET2015 dataset (global, ~200 sites, free for research)
- ChinaFLUX (Chinese flux tower network, ~40 sites)
- AmeriFlux (North American sites)

**Chinese FLUXNET sites relevant to HydroCraft**:

| Site | Code | Biome | Lat | Lon | Elev (m) | Years |
|------|------|-------|-----|-----|----------|-------|
| Changbaishan | CBS | Temperate mixed forest | 42.40 | 128.10 | 738 | 2003-2010 |
| Qianyanzhou | QYZ | Subtropical evergreen forest | 26.74 | 115.06 | 102 | 2003-2010 |
| Dinghushan | DHS | Subtropical evergreen broadleaf | 23.17 | 112.53 | 300 | 2003-2010 |
| Haibei | HB | Alpine meadow | 37.62 | 101.30 | 3250 | 2002-2010 |
| Dangxiong | DX | Alpine grassland | 30.50 | 91.07 | 4333 | 2004-2010 |
| Xishuangbanna | XSBN | Tropical rainforest | 21.93 | 101.27 | 756 | 2003-2010 |

**Validation metrics**:
- R2 and RMSE for daily/monthly GPP, NEE, ET
- Annual totals comparison (GPP, NPP, NEE)
- Seasonal cycle amplitude and phase
- Interannual variability correlation

**Tools to build**:
- `download_fluxnet_site.py` — Download and parse FLUXNET2015 CSV for a site
- `compare_bgc_fluxnet.py` — Compute R2, RMSE, bias for GPP/NEE/ET
- `plot_bgc_fluxnet_comparison.py` — Time series + scatter plots

### S9: VIC/HydroCraft Coupling

**Purpose**: Run BIOME-BGC within the HydroCraft multi-model framework.

**Knowledge type**: Evaluative (coupling strategy, double-counting avoidance) + Procedural (format conversion)

**Coupling pathways**:

#### VIC -> BIOME-BGC (one-way, primary)
1. **Meteorological forcing**: VIC forcing files (7-col ASCII, 3-hourly) -> BIOME-BGC daily met
   - Aggregate sub-daily to daily (min/max T, sum precip, mean radiation, etc.)
   - Convert units: K->C, mm->cm, specific_humidity->VPD, add day length

2. **Soil properties**: VIC soil params (or HWSD directly) -> BIOME-BGC .ini site section
   - Sand/silt/clay percentages
   - Soil depth (use VIC layer 2+3 depth sum)

3. **Soil moisture initial conditions**: VIC output soil moisture -> BIOME-BGC initial soil water fraction

4. **Land cover mapping**: VIC vegetation parameter file (AVHRR classes) -> BIOME-BGC PFT selection per grid cell

#### BIOME-BGC -> VIC (feedback, advanced)
- Not standard, but possible: BIOME-BGC LAI -> VIC vegetation parameter (dynamic LAI)
- BIOME-BGC ET can be compared with VIC ET for consistency checks

#### BIOME-BGC vs MODIS (validation)
- Compare BIOME-BGC GPP with MODIS MOD17A2 GPP product (8-day, 500m)
- Compare BIOME-BGC LAI with MODIS MOD15A2 LAI product

**Double-counting prevention**:
- VIC and BIOME-BGC both compute ET and soil water. When coupled, decide which model "owns" the water balance:
  - **Recommended**: VIC owns the water balance (routing, discharge). BIOME-BGC is run diagnostically for carbon fluxes using VIC's meteorological forcing. Do NOT feed BIOME-BGC ET back to VIC.
  - **Alternative**: Use BIOME-BGC ET to replace VIC ET for forest cells (more physically realistic for forests, but complex).

**Tools to build**:
- `vic_forcing_to_bgc_met.py` — VIC 7-col ASCII -> BIOME-BGC .mtcNN (per grid cell)
- `vic_soil_to_bgc_site.py` — VIC soil params -> BIOME-BGC .ini site section
- `vic_landcover_to_bgc_pft.py` — VIC veg params -> BIOME-BGC PFT mapping
- `run_bgc_on_vic_grid.py` — Orchestrate: loop over VIC cells, run BIOME-BGC per cell, aggregate
- `compare_bgc_modis_gpp.py` — Download MODIS GPP, compare with BIOME-BGC

### S10: LDNDC Boundary Coupling

**Purpose**: Coordinate BIOME-BGC (forest/grassland) with LDNDC (cropland) at landscape scale.

**Knowledge type**: Evaluative (land cover delineation, C budget aggregation)

**Strategy**:
- Within a basin, each VIC grid cell has a dominant land cover type
- Forest/grassland cells -> BIOME-BGC
- Cropland cells -> LDNDC
- Each model runs independently on its assigned cells
- Basin-wide C/N budget = area-weighted sum of all cells

**Tools to build**:
- `partition_grid_by_landcover.py` — Split VIC grid cells into BIOME-BGC vs LDNDC domains
- `aggregate_basin_carbon_budget.py` — Combine BIOME-BGC + LDNDC outputs for basin total

---

## 4. Complete Tools Inventory

| ID | Tool Name | Stage | Lines (est.) | Purpose |
|----|-----------|-------|-------------|---------|
| t01 | `generate_ini_file.py` | S1 | 200 | Generate .ini from structured inputs |
| t02 | `hwsd_to_bgc_site.py` | S1 | 150 | HWSD soil -> BIOME-BGC site params |
| t03 | `generate_epc_file.py` | S2 | 300 | Generate .epc for a PFT with defaults + overrides |
| t04 | `map_landcover_to_pft.py` | S2 | 200 | AVHRR/MODIS land cover -> BIOME-BGC PFT |
| t05 | `convert_cmfd_to_bgc_met.py` | S3 | 250 | CMFD 3-hourly -> BIOME-BGC daily met |
| t06 | `convert_mswx_to_bgc_met.py` | S3 | 250 | MSWX 3-hourly -> BIOME-BGC daily met |
| t07 | `convert_vic_forcing_to_bgc_met.py` | S3 | 200 | VIC forcing -> BIOME-BGC met |
| t08 | `compute_daylength.py` | S3 | 80 | Astronomical day length from lat + DOY |
| t09 | `compute_vpd.py` | S3 | 60 | VPD from T + humidity |
| t10 | `generate_co2_file.py` | S4 | 100 | Annual CO2 lookup table |
| t11 | `run_spinup.py` | S5 | 350 | Execute spinup with convergence monitoring |
| t12 | `check_spinup_convergence.py` | S5 | 150 | Analyze spinup for steady-state |
| t13 | `manage_restart_files.py` | S5 | 100 | Handle restart file I/O |
| t14 | `run_bgc.py` | S6 | 150 | Execute BIOME-BGC with error handling |
| t15 | `run_bgc_grid.py` | S6 | 300 | Gridded execution over VIC cells |
| t16 | `parse_daily_output.py` | S7 | 200 | Parse daily output to DataFrame |
| t17 | `parse_annual_output.py` | S7 | 100 | Parse annual output |
| t18 | `compute_carbon_budget.py` | S7 | 200 | Annual C budget + mass balance |
| t19 | `compare_bgc_fluxnet.py` | S8 | 250 | FLUXNET validation (R2, RMSE, bias) |
| t20 | `vic_forcing_to_bgc_met.py` | S9 | 250 | VIC forcing -> BIOME-BGC met (coupling) |
| t21 | `run_bgc_on_vic_grid.py` | S9 | 400 | Orchestrate gridded BIOME-BGC on VIC |
| t22 | `partition_grid_by_landcover.py` | S10 | 200 | Split cells into BGC vs LDNDC domains |
| t23 | `aggregate_basin_carbon_budget.py` | S10 | 250 | Basin-wide C budget (BGC + LDNDC) |

**Total**: ~23 tools, ~4,290 estimated lines

---

## 5. Skill Documents

| ID | Document | Stage | Focus Areas | Est. Words |
|----|----------|-------|-------------|------------|
| sd01 | `s1_site_definition_skill.md` | S1 | INI file format (line-by-line), soil from HWSD, N deposition sources | 1500 |
| sd02 | `s2_ecophysiology_params_skill.md` | S2 | PFT selection strategy, EPC parameter meaning, sensitivity ranking, AVHRR mapping | 2000 |
| sd03 | `s3_meteorological_forcing_skill.md` | S3 | Unit conversion table (CRITICAL), VPD computation, day length, Tday approximation | 1800 |
| sd04 | `s4_co2_concentration_skill.md` | S4 | Historical CO2 lookup, CMIP6 SSP pathways, spinup CO2 (280 ppm) | 800 |
| sd05 | `s5_spinup_strategy_skill.md` | S5 | **MOST IMPORTANT DOC** — convergence criteria by biome, acceleration, restart management, troubleshooting non-convergence | 3000 |
| sd06 | `s6_execution_skill.md` | S6 | Run command, expected runtime, output file structure, error codes | 1200 |
| sd07 | `s7_output_analysis_skill.md` | S7 | Variable definitions, physical ranges, C budget closure, derived metrics (CUE, WUE) | 1500 |
| sd08 | `s8_fluxnet_validation_skill.md` | S8 | FLUXNET data access, site selection for Chinese basins, validation metrics, publication standards | 1500 |
| sd09 | `s9_vic_coupling_skill.md` | S9 | Coupling strategy, double-counting ET, grid orchestration, MODIS comparison | 2000 |
| sd10 | `s10_ldndc_boundary_skill.md` | S10 | Land cover partitioning, C budget aggregation, ag-forest boundary handling | 1200 |

**Total**: 10 skill documents, ~16,500 estimated words

**Priority for sd05 (Spinup Strategy)**: This is the document that most differentiates BIOME-BGC from other HydroCraft models. No other model in the platform requires multi-century spinup. The document should cover:
- Why spinup is necessary (SOC pool timescales)
- How to determine if spinup has converged (metrics + thresholds)
- What happens if you skip or truncate spinup (inflated/deflated NEE)
- Spinup acceleration (Thornton & Rosenbloom 2005 method)
- Biome-specific spinup durations
- Common spinup failures (oscillating C pools, negative N pools)
- Restart file chain: spinup endpoint -> normal run restart input

---

## 6. Diagnostic Triplets (Anticipated)

### Compilation & Setup (dt_001 - dt_003)

| ID | Symptom | Diagnosis | Remedy | Severity |
|----|---------|-----------|--------|----------|
| dt_001 | `make` fails with "implicit declaration of function" | C99/C11 strict mode conflicts with ANSI C code | Add `-std=gnu89` or `-Wno-implicit-function-declaration` to CFLAGS | fatal |
| dt_002 | Model runs but immediately exits with no output | .ini file path to .epc or .met file is wrong or file missing | Check all file paths in .ini (lines 3, 14); use absolute paths | fatal |
| dt_003 | Segfault on startup | Soil sand+silt+clay != 100 or negative value in .ini | Validate that sand+silt+clay = 100 exactly | fatal |

### INI File Parsing (dt_004 - dt_006)

| ID | Symptom | Diagnosis | Remedy | Severity |
|----|---------|-----------|--------|----------|
| dt_004 | Model reads, runs, but all fluxes are wrong magnitude | **INI file line off-by-one** — extra blank line or comment shifts all parameters | Count lines exactly; compare with reference .ini; validate each param range | **silent** |
| dt_005 | Very high/low GPP but model completes normally | CO2 line in .ini has wrong units (ppm vs fraction vs Pa) | BIOME-BGC 4.2 expects ppm; verify value ~280-600 for historical | **silent** |
| dt_006 | Extremely high transpiration, soil dries instantly | Soil depth in .ini is in cm instead of m (100x too shallow) | BIOME-BGC expects meters; verify depth 0.5-3.0 m | **silent** |

### Meteorological Forcing (dt_007 - dt_011)

| ID | Symptom | Diagnosis | Remedy | Severity |
|----|---------|-----------|--------|----------|
| dt_007 | GPP/NPP ~10x higher than literature | **Precipitation in mm instead of cm** | Divide by 10; BIOME-BGC expects cm/day | **silent** |
| dt_008 | Stomata always fully open, ET unrealistically high | **VPD in kPa instead of Pa** | Multiply by 1000; BIOME-BGC expects Pa | **silent** |
| dt_009 | No photosynthesis (GPP=0), LAI grows normally | Day length column is 0 or missing | Compute day length from latitude + DOY using astronomical formula | **silent** |
| dt_010 | Temperature-dependent processes wrong (phenology, respiration) | **Temperature in K instead of C** | Subtract 273.15; BIOME-BGC expects Celsius | **silent** |
| dt_011 | Met file parsing error or wrong number of columns | Whitespace/delimiter mismatch (tabs vs spaces, trailing newlines) | Ensure space-separated with consistent formatting | fatal |

### Spinup (dt_012 - dt_016)

| ID | Symptom | Diagnosis | Remedy | Severity |
|----|---------|-----------|--------|----------|
| dt_012 | Spinup never converges (SOC keeps increasing after 6000 years) | N deposition too high for pre-industrial conditions | Use pre-industrial N deposition (~0.0002 kgN/m2/yr), not modern values (~0.001+) | degraded |
| dt_013 | Spinup converges but negative soil N pools | N immobilization exceeds total N input over centuries | Reduce litter C:N ratio or increase N fixation parameter | degraded |
| dt_014 | NEE strongly positive for first 50+ years of normal run after spinup | Spinup converged at different CO2 than normal run; C pools adjusting | Use same CO2 for last spinup cycle as first year of normal run; or run 50-yr "transition" | degraded |
| dt_015 | Restart file read error or garbage values | Restart file from incompatible BIOME-BGC version or corrupted | Ensure same binary produced the restart; check file size matches expected | fatal |
| dt_016 | Spinup oscillates (SOC cycles up/down without converging) | Met data has extreme years that alternately build/deplete pools | Use longer met record (20+ years) for spinup cycling; smooth extremes | degraded |

### Ecophysiology & Phenology (dt_017 - dt_019)

| ID | Symptom | Diagnosis | Remedy | Severity |
|----|---------|-----------|--------|----------|
| dt_017 | Deciduous forest has no leaf-off period | Soil temperature never drops below onset threshold (tropical application of temperate params) | Adjust phenology parameters for tropical; or use EBF PFT instead of DBF | **silent** |
| dt_018 | GPP much higher than FLUXNET for same biome/climate | SLA (specific leaf area) too high for the PFT | Check SLA units (m2/kgC); typical: ENF=8-12, DBF=20-40, grass=25-45 | **silent** |
| dt_019 | Unrealistic allocation (all C to wood, no leaves) | Allocation ratio parameters in .epc are transposed or wrong | Verify new_froot_C:new_leaf_C (~1.0-1.5) and new_stem_C:new_leaf_C (~2-4 for forests) | **silent** |

### Coupling (dt_020 - dt_025)

| ID | Symptom | Diagnosis | Remedy | Severity |
|----|---------|-----------|--------|----------|
| dt_020 | Basin ET much higher than VIC ET when BIOME-BGC added | **Double-counting**: both VIC and BIOME-BGC computing ET from same forcing | Use VIC ET for water balance; BIOME-BGC ET is diagnostic only | **silent** |
| dt_021 | BIOME-BGC GPP for cropland cells is unrealistic | Running BIOME-BGC on cropland (should use LDNDC/DSSAT) | Filter cells by land cover; BIOME-BGC for AVHRR classes 1-10 only | degraded |
| dt_022 | Basin total C budget has gaps in spatial coverage | Some VIC cells have no BIOME-BGC or LDNDC assignment | Ensure partition_grid_by_landcover assigns every land cell | warning |
| dt_023 | MODIS GPP much higher than BIOME-BGC in tropical forests | BIOME-BGC default ENF/DBF params from temperate, not tropical | Use tropical EPC parameters (higher SLA, no cold limitation) | degraded |
| dt_024 | Soil water differs greatly between VIC and BIOME-BGC | Different soil water models (VIC: 3-layer variable infiltration, BGC: single bucket) | Accept difference; use VIC for hydrological routing, BGC for C flux only | warning |
| dt_025 | BIOME-BGC runs on grid cell but AVHRR says "water" | Water body cell given to BIOME-BGC | Skip water/urban/bare cells (AVHRR classes 12-14) | warning |

**Total**: 25 anticipated diagnostic triplets across 6 failure domains

---

## 7. Coupling Points Summary

### Inbound Couplings (other models -> BIOME-BGC)

| Source | Data | Conversion | Tool |
|--------|------|-----------|------|
| VIC forcing | 7-col ASCII, 3-hourly | Aggregate to daily, convert units (K->C, mm->cm, Pa VPD, add daylen) | `vic_forcing_to_bgc_met.py` |
| CMFD | NetCDF, 3-hourly, 0.1deg | Extract grid cell, aggregate, convert units | `convert_cmfd_to_bgc_met.py` |
| MSWX | NetCDF, 3-hourly, 0.1deg | Extract grid cell, aggregate, convert units | `convert_mswx_to_bgc_met.py` |
| HWSD | Global raster + MDB | Sand/silt/clay/pH/OC for site location | `hwsd_to_bgc_site.py` |
| VIC soil params | 53-col ASCII | Texture, depth, bulk density | `vic_soil_to_bgc_site.py` |
| AVHRR land cover | 1km raster | Classify each cell -> PFT | `map_landcover_to_pft.py` |
| CMIP6 projections | Delta-change method | Future met + CO2 | Reuse climate-projection skill |

### Outbound Couplings (BIOME-BGC -> other models)

| Target | Data | Purpose |
|--------|------|---------|
| LDNDC | Forest/grassland cell assignment | Partition land cover |
| VIC (advanced) | Dynamic LAI | Update VIC veg params with BIOME-BGC phenology |
| MODIS comparison | Gridded GPP/LAI | Spatial validation |
| Basin C budget | Cell-level GPP, NPP, NEE, SOC | Aggregate with LDNDC for total |

### Validation Couplings

| Validation Source | Variable | Tool |
|-------------------|----------|------|
| FLUXNET/ChinaFLUX | GPP, NEE, ET (daily) | `compare_bgc_fluxnet.py` |
| MODIS MOD17A2 | GPP (8-day, 500m) | `compare_bgc_modis_gpp.py` |
| Forest inventory data | Biomass, SOC stocks | Manual comparison |

---

## 8. Validation Plan

### Step 1: Developer Data Test

Run BIOME-BGC 4.2 with the bundled example data (temperate ENF or DBF). Verify the binary compiles, runs, and produces output with reasonable values:
- GPP: 1000-2000 gC/m2/yr
- NEE: -100 to -400 gC/m2/yr (sink)
- ET: 400-800 mm/yr
- LAI peak: 3-8 m2/m2

### Step 2: Progressive Data Replacement

Replace inputs one at a time with HydroCraft data, verifying after each:

1. **Replace met forcing** with CMFD (Bengbu region, 2000-2010, nearest forest cell)
   - Use `convert_cmfd_to_bgc_met.py`
   - Verify temperature, precip, radiation against CMFD diagnostics

2. **Replace soil** with HWSD for Bengbu
   - Use `hwsd_to_bgc_site.py`
   - Verify sand/clay/depth are reasonable

3. **Replace CO2** with historical Mauna Loa values
   - Use `generate_co2_file.py`

4. **Replace EPC** with auto-selected PFT from AVHRR
   - Use `map_landcover_to_pft.py`

### Step 3: Full HydroCraft Data Run

**Primary test basin**: Bengbu (but target FOREST cells within the basin, not cropland)

The Bengbu basin (Huai River, 121,330 km2) is predominantly cropland, so BIOME-BGC would apply to a small fraction of cells. For a more meaningful test:

**Alternative/additional test basins for forest validation**:

| Basin | Forest type | FLUXNET site nearby | Justification |
|-------|-----------|---------------------|---------------|
| Changbai Mountains (长白山) | Temperate mixed forest | CBS (42.4N, 128.1E) | ChinaFLUX validated, near Songhua River basin |
| Qianyanzhou (千烟洲) | Subtropical plantation | QYZ (26.7N, 115.1E) | Well-studied Chinese forest flux site |
| Heihe upper basin (黑河上游) | Alpine meadow/shrub | Haibei HB (37.6N, 101.3E) | Already validated with VIC in HydroCraft |

**Validation criteria**:
- GPP within 30% of FLUXNET annual total (uncalibrated)
- Seasonal cycle phase within 15 days of FLUXNET
- LAI seasonal amplitude within 50% of MODIS
- NEE sign correct (sink for forests)

### Step 4: Coupled Run (VIC + BIOME-BGC)

Run on a basin with mixed land cover:
1. Run VIC for full basin
2. Partition cells: forest/grassland -> BIOME-BGC, cropland -> LDNDC
3. Run BIOME-BGC on forest cells using VIC forcing
4. Aggregate basin carbon budget
5. Compare basin-average GPP with MODIS MOD17A2

---

## 9. Estimated Effort

| Phase | Tasks | Estimated Time |
|-------|-------|---------------|
| **Phase 0: Installation** | Download, compile, test with bundled examples | 2 hours |
| **Phase 1: Pipeline Mapping** | Verify source code structure, map I/O formats, dependency matrix | 3 hours |
| **Phase 2: Knowledge Classification** | Classify each stage's procedural/evaluative/debugging knowledge | 2 hours |
| **Phase 3: Tool Extraction** | Build 23 tools (~4,300 lines) | 20 hours |
| **Phase 4: Skill Documents** | Write 10 documents (~16,500 words), especially spinup strategy | 12 hours |
| **Phase 5: Diagnostic Triplets** | Build 25 triplets, verify against common failure patterns | 4 hours |
| **Phase 6: Validation** | Developer test + progressive replacement + full HydroCraft run + FLUXNET comparison | 15 hours |

**Total estimated**: ~58 hours (~7 working days)

### Priority Order for Implementation

1. **S3 (Met forcing)** — This is where unit traps live. Build and validate first.
2. **S1 (Site definition)** — INI file generator with rigorous line-count validation.
3. **S2 (Ecophysiology)** — EPC generator + land cover mapping.
4. **S5 (Spinup)** — The most complex and unique stage. Build with convergence monitoring.
5. **S6 (Execution)** — Simple wrapper once inputs are ready.
6. **S7 (Output parsing)** — Straightforward column parsing.
7. **S9 (VIC coupling)** — The integration point with HydroCraft.
8. **S8 (FLUXNET validation)** — Final quality check.
9. **S4 (CO2)** — Reuse LDNDC airchemistry tool.
10. **S10 (LDNDC boundary)** — Final integration.

---

## 10. Critical Domain Knowledge (Pre-Dissection Notes)

### 10.1 The Precipitation Unit Trap

BIOME-BGC uses **cm/day** for precipitation. This is unusual — most Earth system models use mm/day or mm/timestep. Every forcing conversion tool MUST include the divide-by-10 step. This single trap will cause the most debugging time if missed. **Add a postcondition check**: if mean annual precipitation > 300 cm (3000 mm), warn that units may be wrong.

### 10.2 The VPD Trap

VPD (vapor pressure deficit) in BIOME-BGC is in **Pascals** (not kPa, not hPa, not mmHg). CMFD/MSWX provide specific humidity (kg/kg) or relative humidity (%). The conversion chain is:
1. Compute saturated vapor pressure from temperature: es = 611 * exp(17.27*T / (T+237.3))
2. Compute actual vapor pressure from specific humidity: ea = q * P / (0.622 + 0.378*q)
3. VPD = es - ea (in Pa)

If VPD is provided in kPa (common in many datasets), it must be multiplied by 1000.

### 10.3 The Spinup Trap

Skipping or truncating spinup is the most common mistake in published BIOME-BGC studies. Signs of inadequate spinup:
- NEE starts very negative (apparent C sink) but trends toward zero over decades
- Soil C pools increase monotonically for the entire simulation
- First 50 years of NEE look completely different from last 50 years

### 10.4 The Line-Number Trap

The .ini file is the single most dangerous input because it has no field names — just values on specific lines. A blank line, comment, or different version's format shifts everything. The tool MUST generate .ini files from structured data, never by text editing. And the tool MUST validate the generated .ini by reading it back and checking ranges.

### 10.5 Forest vs Crop: Complementary Domains

When presenting BIOME-BGC results, always clarify:
- BIOME-BGC = natural ecosystems (forests, grasslands, shrublands)
- LDNDC = managed agricultural systems (crops + fertilizer + tillage)
- DSSAT/WOFOST = crop yield and irrigation optimization
- For a full basin C budget, you need BIOME-BGC + LDNDC together

---

## 11. Integration with Knowledge Infrastructure YAML

The final `knowledge_infrastructure.yaml` will follow the schema at `KISSPATH_INTERNAL_NOT_SHIPPED/schema/knowledge_infrastructure.yaml` with:

```yaml
package:
  name: "biome-bgc-knowledge-infrastructure"
  version: "1.0.0"
  description: "Knowledge infrastructure for BIOME-BGC terrestrial biogeochemistry model with VIC/LDNDC coupling in HydroCraft"
  target_model: "BIOME-BGC 4.2"
  domain: "terrestrial biogeochemistry, forest carbon cycling, natural ecosystem C/N/water fluxes, FLUXNET validation"
  authors:
    - "HydroCraft Team (Jianyun Zhang Research Group)"
    - "Claude (Knowledge Dissection)"
  license: "CC-BY-4.0"

pipeline:
  stages: [s1_site_definition, s2_ecophysiology_params, s3_meteorological_forcing, s4_co2_concentration, s5_spinup_execution, s6_normal_execution, s7_output_analysis, s8_fluxnet_validation, s9_vic_coupling, s10_ldndc_boundary]

summary:
  total_tools: 23
  total_tool_lines: ~4300
  total_skill_documents: 10
  total_skill_words: ~16500
  total_diagnostic_triplets: 25
  failure_domains: [compilation, path_resolution, unit_conversion, parameter_format, spinup_convergence, coupling_double_counting, silent_error]
  pipeline_stages: 10
  pipeline_milestones: ~25
```

---

## 12. Final Package Structure (Target)

```
models/BIOME_BGC/knowledge_infrastructure/
  SKILL.md                           # Agent entry point
  DISSECTION_PLAN.md                 # This document
  knowledge_infrastructure.yaml      # Populated schema
  workflow/
    pipeline.drawio                  # Visual workflow diagram
    workflow.md                      # Agent-readable workflow
  tools/
    s1_site_definition/
      generate_ini_file.py
      hwsd_to_bgc_site.py
    s2_ecophysiology_params/
      generate_epc_file.py
      map_landcover_to_pft.py
    s3_meteorological_forcing/
      convert_cmfd_to_bgc_met.py
      convert_mswx_to_bgc_met.py
      convert_vic_forcing_to_bgc_met.py
      compute_daylength.py
      compute_vpd.py
    s4_co2_concentration/
      generate_co2_file.py
    s5_spinup_execution/
      run_spinup.py
      check_spinup_convergence.py
      manage_restart_files.py
    s6_normal_execution/
      run_bgc.py
      run_bgc_grid.py
    s7_output_analysis/
      parse_daily_output.py
      parse_annual_output.py
      compute_carbon_budget.py
      compute_flux_statistics.py
    s8_fluxnet_validation/
      compare_bgc_fluxnet.py
    s9_vic_coupling/
      vic_forcing_to_bgc_met.py
      run_bgc_on_vic_grid.py
    s10_ldndc_boundary/
      partition_grid_by_landcover.py
      aggregate_basin_carbon_budget.py
  docs/
    s1_site_definition_skill.md
    s2_ecophysiology_params_skill.md
    s3_meteorological_forcing_skill.md
    s4_co2_concentration_skill.md
    s5_spinup_strategy_skill.md       # MOST IMPORTANT
    s6_execution_skill.md
    s7_output_analysis_skill.md
    s8_fluxnet_validation_skill.md
    s9_vic_coupling_skill.md
    s10_ldndc_boundary_skill.md
  diagnostics/
    triplets.yaml                    # 25 diagnostic triplets
    error_log.yaml                   # Populated during validation
    episodes.yaml                    # Debugging stories
  epc/                               # Default EPC parameter files
    enf_temperate.epc
    dbf_temperate.epc
    ebf_tropical.epc
    c3grass.epc
    c4grass.epc
    shrub.epc
    dnf_boreal.epc
  lib/                               # Shared utilities
    bgc_constants.py                 # Physical constants, unit conversions
    met_utils.py                     # Day length, VPD, Tday computation
```

---

*This dissection plan was prepared for the HydroCraft platform by the Jianyun Zhang Research Group using the Knowledge Dissection Toolkit v1.0. BIOME-BGC extends HydroCraft's biogeochemistry capability from cropland (LDNDC) to natural ecosystems (forests, grasslands, shrublands), enabling full-basin carbon budgets and FLUXNET validation.*
