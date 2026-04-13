# GLM (General Lake Model) — Knowledge Dissection Plan

**Package**: `hydrocraft-glm-lake` v0.1.0
**Target model**: GLM v3.3.x + AED2 water quality library
**Priority**: #1 — HydroCraft has ZERO lake/reservoir modeling capability; reservoirs are critical for Chinese water resources
**Created**: 2026-03-21
**Author**: Jianyun Zhang Research Group, Hohai University

---

## 1. Model Overview

### What GLM Does

GLM (General Lake Model) is a 1D vertical hydrodynamic model for lakes and reservoirs. It simulates:

- **Thermal stratification**: Vertically resolved temperature profiles through the water column using a flexible Lagrangian layer scheme (layers merge/split dynamically)
- **Mixing dynamics**: Surface mixing (wind stirring, convective overturn), shear-driven mixing, Kelvin-Helmholtz instabilities, and deep hypolimnetic mixing
- **Water balance**: Inflows, outflows, rainfall, evaporation, seepage — tracks lake level and volume
- **Ice cover**: Snow-ice formation, white ice, blue ice growth/decay, albedo feedback
- **Light penetration**: Multi-band extinction with Beer-Lambert law, Secchi depth
- **Sediment heat flux**: Seasonal sediment temperature cycle, benthic boundary layer
- **Inflow dynamics**: Density-driven insertion of river inflows at the appropriate depth (plunging, interflow, or overflow)
- **Outflow dynamics**: Withdrawal at specified elevations, floating offtakes, overflow/spillway

### AED2 Water Quality Coupling

GLM couples dynamically with the AED (Aquatic EcoDynamics) library for biogeochemical simulation:

- Dissolved oxygen (DO) — atmospheric exchange, sediment oxygen demand, biological production/consumption
- Nutrients — nitrogen (NO3, NH4, DON, PON), phosphorus (PO4, DOP, POP), silica
- Phytoplankton — multiple functional groups (diatoms, cyanobacteria, green algae), growth/respiration/mortality
- Organic matter — dissolved/particulate, labile/refractory decomposition
- Carbon — DIC, DOC, POC, pH, alkalinity
- Sediment diagenesis — nutrient release from bottom sediments
- Pathogens, heavy metals, and other water quality constituents

### Technical Specifications

| Attribute | Value |
|-----------|-------|
| Language | C (77%), Fortran (20%), Shell (2%), Makefile (1%) |
| Current version | v3.3.3 (Ubuntu .deb, 2024); stable release v3.3.0 (2022-09-04) |
| Reference paper | Hipsey et al. (2019), Geoscientific Model Development, 12(1), 473-523 |
| License | GPL-3.0 |
| Repository | https://github.com/AquaticEcoDynamics/GLM (source), https://github.com/AquaticEcoDynamics/glm-aed (release + examples) |
| Pre-built binaries | Ubuntu 20.04, 22.04, 24.04 (.deb packages) |
| Config format | Fortran namelist (glm3.nml) |
| Forcing format | CSV (meteorological, inflow, outflow) |
| Output format | NetCDF (output.nc) + CSV (lake.csv, WQ_*.csv, outlet_*.csv) |
| Timestep | Configurable, typically 3600s (1 hour) |
| Spatial dimension | 1D vertical (up to 500 layers, adaptive Lagrangian) |
| Companion tools | glmtools (R), no official Python package yet |

---

## 2. Why GLM is Critical for HydroCraft

### Gap Analysis

HydroCraft currently has 19 model packages covering hydrology, routing, crops, water quality, biogeochemistry, groundwater, urban drainage, and glaciology. However:

1. **No lake/reservoir process model**: CaMa-Flood routes water through river channels and floodplains but treats lakes as simple storage-discharge curves. There is no thermal stratification, no mixing physics, no vertical temperature profiles.

2. **Reservoir operations dominate Chinese hydrology**: Three Gorges (39.3 km^3), Danjiangkou (33.9 km^3), Xiaolangdi, Longyangxia, and hundreds of medium reservoirs regulate flow on every major Chinese river. Without lake modeling, HydroCraft cannot accurately simulate:
   - Downstream temperature regime (cold-water releases affect ecology)
   - Nutrient retention/release by reservoirs
   - Seasonal stratification and turnover timing
   - Ice cover duration in northern reservoirs
   - Climate change impacts on lake thermal structure

3. **Water quality coupling**: SWAT+ and RZWQM2 handle field-scale/watershed nutrient transport but stop at the lake boundary. GLM+AED2 provides the missing in-lake biogeochemistry.

4. **Global lake databases exist**: HydroLAKES (~1.4 million lakes globally, with depth, area, volume, shoreline) enables automated parameterization for any lake worldwide — fits the HydroCraft "zero manual data prep" philosophy.

### Strategic Value

Adding GLM makes HydroCraft the first AI platform capable of end-to-end simulation from precipitation through hillslope runoff (VIC) through river routing (CaMa-Flood) through lake/reservoir processes (GLM) to downstream water quality — fully autonomous, for any basin worldwide.

---

## 3. Installation Plan

### Option A: Pre-built Ubuntu Binary (Recommended)

```bash
# Download from GitHub
wget https://github.com/AquaticEcoDynamics/glm-aed/raw/main/binaries/ubuntu/22.04/glm_3.3.3-0_amd64.deb

# Install
sudo dpkg -i glm_3.3.3-0_amd64.deb

# Verify
glm --help
```

The .deb package includes both GLM and the AED water quality library. Expected install location: `/usr/bin/glm` or `/usr/local/bin/glm`.

### Option B: Compile from Source

```bash
git clone --recurse-submodules https://github.com/AquaticEcoDynamics/glm-aed.git
cd glm-aed/glm-source
./build_glm.sh
```

**Dependencies**: C compiler (gcc), Fortran compiler (gfortran), NetCDF-C library, NetCDF-Fortran library.

### Recommended Path

**Start with Option A** (pre-built binary). Only compile from source if the .deb package has library incompatibilities with the server's Ubuntu version. The server runs a recent kernel (6.17.0), so Ubuntu 22.04 or 24.04 .deb should work.

### Target Installation Location

```
model/glm/
  bin/glm                          # GLM-AED executable
  examples/                        # Reference examples from glm-aed repo
    Sparkling/                     # Sparkling Lake (Wisconsin, USA)
    FCR/                           # Falling Creek Reservoir (Virginia, USA)
    Grosse_Dhuenn/                  # Grosse Dhuenn Reservoir (Germany)
    Woods_Lake/                    # Woods Lake
    Lake_Alexandrina/              # Lake Alexandrina (Australia)
```

### Python Dependencies

```
netCDF4, numpy, pandas, xarray, geopandas, shapely, requests
```

All already available in the HydroCraft venv. No additional Python packages needed for core GLM operation (the model is a standalone C binary). For output analysis, consider adding `glmpy` or building a lightweight parser.

---

## 4. Pipeline Stages

### Stage Overview

| # | Stage ID | Name | Description | Tools |
|---|----------|------|-------------|-------|
| 0 | s0_config | Configuration | Lake selection, period, data sources | (manual / config script) |
| 1 | s1_lake_identification | Lake identification & morphometry | HydroLAKES lookup, depth-area curve | `lookup_hydrolakes`, `build_morphometry` |
| 2 | s2_met_forcing | Meteorological forcing | CMFD/MSWX/NASA POWER to GLM met CSV | `convert_met_to_glm` |
| 3 | s3_inflow | Inflow preparation | CaMa-Flood/VIC discharge + temperature to GLM inflow CSV | `convert_inflow_to_glm` |
| 4 | s4_outflow | Outflow configuration | Dam operation rules, spillway, withdrawal depths | `configure_outflow` |
| 5 | s5_init_profiles | Initial conditions | Temperature/salinity/WQ depth profiles | `build_init_profiles` |
| 6 | s6_namelist | GLM namelist generation | Build glm3.nml from all inputs | `generate_glm_nml` |
| 7 | s7_aed_config | AED2 configuration (optional) | Build aed2.nml + aed2_phyto_pars.nml | `generate_aed_config` |
| 8 | s8_execution | GLM execution | Run GLM binary, monitor, collect output | `run_glm` |
| 9 | s9_output_analysis | Output analysis | Parse output.nc, lake.csv; thermal profiles, ice, WQ | `parse_glm_output`, `plot_glm_results` |
| 10 | s10_coupling | Downstream coupling | GLM outflow temperature/WQ back to CaMa-Flood/SWAT+ | `glm_to_cama_outflow` |

### Stage Dependencies

```
s0_config
  |
  +---> s1_lake_identification
  |       |
  |       +---> s5_init_profiles
  |       +---> s6_namelist
  |
  +---> s2_met_forcing --------+
  |                            |
  +---> s3_inflow -------------+---> s6_namelist ---> s8_execution ---> s9_output_analysis
  |                            |                                              |
  +---> s4_outflow ------------+                                              v
  |                            |                                     s10_coupling
  +---> s7_aed_config ---------+
```

Stages s1, s2, s3, s4, s5, s7 can run in parallel after s0.
Stage s6 depends on s1-s5 (and optionally s7).
Stage s8 depends on s6.
Stages s9 and s10 depend on s8.

---

## 5. Detailed Stage Specifications

### s0_config: Configuration

**User inputs required**:
- Lake name or coordinates (lat/lon)
- Simulation period (start_date, end_date)
- Forcing dataset (CMFD / MSWX / NASA POWER)
- Enable AED2 water quality (yes/no)
- Observed data path (optional, for validation)

**Output**: Configuration dictionary / JSON consumed by all downstream stages.

### s1_lake_identification: Lake Identification & Morphometry

**Purpose**: Find the lake in a global database and extract morphometric parameters (depth-area hypsographic curve, surface area, volume, mean/max depth).

**Data sources** (priority order):
1. **HydroLAKES** — ~1.4 million lakes globally, surface area >= 0.1 km^2. Contains: Hylak_id, Lake_name, Country, Pour_lat, Pour_lon, Lake_area (km^2), Shore_len (km), Vol_total (mcm), Vol_res (mcm for reservoirs), Depth_avg (m), Dis_avg (m^3/s), Res_time (days), Elevation (m), Shore_dev (shoreline development ratio), Lake_type (1=Lake, 2=Reservoir, 3=Lake control). Shapefile format.
   - **Path (to download)**: https://www.hydroshare.org/resource/d2a4a2a7e5eb4ae8b74de0f78e08ee07/ or https://data.hydrosheds.org/file/hydrolakes/
   - **Recommended local path**: `data/lakes/HydroLAKES_polys_v10.shp`

2. **GRanD** (Global Reservoir and Dam Database) — ~7,300 large reservoirs globally. Has dam height, year of completion, purpose, capacity. Complementary to HydroLAKES for reservoir-specific attributes.
   - **Path**: `data/lakes/GRanD_v1.3.shp` (to download)

3. **China Lake Database** — For Chinese lakes/reservoirs not well-represented in HydroLAKES. Ministry of Water Resources registry of ~98,000 reservoirs.

**Hypsographic curve construction**:
GLM requires elevation (H) vs. area (A) pairs defining the basin shape. Three approaches:
1. **From DEM**: If the lake is in the DEM (china_dem_90m or Copernicus GLO-30), contour the lakebed bathymetry. Often the DEM only has the water surface — limited use.
2. **Idealized shape**: From HydroLAKES (area, depth, volume), fit a standard shape:
   - Conical: `A(z) = A_surface * (z / z_max)^2`
   - Trapezoidal: `A(z) = A_surface * (a + (1-a) * z / z_max)^2` where `a = A_bottom / A_surface`
   - Cylindrical: `A(z) = A_surface` (constant, for very shallow lakes)
3. **Published bathymetry**: For well-studied lakes (Taihu, Chaohu, Three Gorges), published depth-area curves exist in literature.

**Output**: `morphometry.json` with H[] and A[] arrays, crest_elev, bsn_len, bsn_wid, lake_name, lat, lon.

### s2_met_forcing: Meteorological Forcing

**Purpose**: Convert HydroCraft forcing data to GLM meteorological CSV format.

**GLM meteorological CSV format** (comma-separated, header row):
```
time,ShortWave,LongWave,AirTemp,RelHum,WindSpeed,Rain,Snow
YYYY-MM-DD HH:MM:SS,W/m2,W/m2,degC,%,m/s,m/day,m/day
```

**Variables and units** (CRITICAL — units differ from VIC/WRF-Hydro):

| GLM Variable | Unit | VIC/CMFD Source | Conversion |
|-------------|------|-----------------|------------|
| ShortWave | W/m^2 | SW_DOWN (W/m^2) | Direct (same unit) |
| LongWave | W/m^2 | LW_DOWN (W/m^2) | Direct (same unit) |
| AirTemp | deg C | AIR_TEMP (deg C) | Direct (VIC already in C) |
| RelHum | % (0-100) | VP (kPa) → RH | `RH = 100 * VP / VP_sat(T)` where `VP_sat = 0.6108 * exp(17.27*T/(T+237.3))` |
| WindSpeed | m/s | WIND (m/s) | Direct |
| Rain | m/day | PRECIP (mm/timestep) | `mm/3hr * 8 / 1000 = m/day` |
| Snow | m/day | (derived from PRECIP + T) | `Rain when T<0` partitioned as snow |

**Critical unit traps**:
- **Rain/Snow in m/day, NOT mm/day**: GLM uses meters per day. Off by 1000x if you use mm/day — lake will flood or dry up.
- **RelHum as percentage, NOT fraction**: Must be 0-100, not 0-1. Off by 100x causes extreme evaporation.
- **LongWave**: GLM can accept incoming LW or compute from cloud cover. If `lw_type = 'LW_IN'`, provide measured/modeled incoming LW. If `lw_type = 'LW_CC'`, provide cloud cover fraction instead.

**Source data options**:
- CMFD (China, 0.1deg, 3-hourly) — already on server at `data/forcing/Data_forcing_03hr_010deg/`
- MSWX (global, 0.1deg, 3-hourly) — already on server at `/mnt/disk3/msxw/`
- NASA POWER (global, 0.5deg, hourly) — API, no local data needed

**Output**: `bcs/met_hourly.csv` in GLM format.

### s3_inflow: Inflow Preparation

**Purpose**: Convert river discharge from VIC/CaMa-Flood to GLM inflow CSV format.

**GLM inflow CSV format**:
```
time,FLOW,TEMP,SALT[,wq_var1,wq_var2,...]
YYYY-MM-DD HH:MM:SS,m3/s,degC,psu,...
```

**Inflow sources** (priority order):
1. **CaMa-Flood output**: `outflw` (m^3/s) from the grid cell(s) flowing into the lake. Already in correct units.
2. **VIC output**: Runoff + baseflow from upstream cells, aggregated and routed to the lake inflow point.
3. **Observed inflow**: If available from gauging stations.

**Inflow temperature estimation** (when not measured):
- **From air temperature**: `T_inflow = a * T_air + b` (linear regression, typical: a=0.9, b=1.5 for temperate lakes)
- **From VIC soil temperature**: Layer 1 soil temp as proxy
- **Seasonal climatology**: Monthly mean inflow temperature from literature

**Multiple inflows**: GLM supports multiple inflow streams (num_inflows). For reservoirs with major tributaries, provide separate CSV files per inflow.

**Inflow insertion physics**: GLM computes the density of the inflowing water (from temperature and salinity), compares it to the lake profile, and inserts the inflow at the depth of neutral buoyancy. Parameters:
- `subm_flag`: Whether the inflow enters below the surface
- `strm_hf_angle`: Stream half-angle (controls plunge geometry)
- `strmbd_slope`: Stream bed slope at entry point
- `strmbd_drag`: Stream bed drag coefficient

**Output**: `bcs/inflow_1.csv` (one per inflow stream).

### s4_outflow: Outflow Configuration

**Purpose**: Configure how water exits the lake/reservoir.

**GLM outflow CSV format**:
```
time,FLOW
YYYY-MM-DD HH:MM:SS,m3/s
```

**Outflow types**:
1. **Fixed-elevation outlet** (dam spillway, pipe): `outl_elvs` specifies the withdrawal elevation
2. **Floating offtake**: Withdraws from near the surface (`flt_off_sw = .true.`)
3. **Overflow/weir**: Broad-crested weir formula when lake level exceeds `crest_elev`
4. **Scheduled releases**: Time-varying outflow from reservoir operation rules

**For Chinese reservoirs**: Operation rules are typically:
- Flood season (Jun-Sep): Maintain level below flood control level, release excess
- Non-flood season: Store water, maintain minimum ecological flow
- Hydropower: Release pattern optimized for power generation

**Coupling with Pywr**: If HydroCraft's Pywr reservoir operation model is available, its release schedule becomes the GLM outflow time series.

**Output**: `bcs/outflow.csv` + outflow parameters in glm3.nml.

### s5_init_profiles: Initial Conditions

**Purpose**: Define initial vertical profiles of temperature, salinity, and (optionally) water quality variables.

**GLM init_profiles block**:
```
&init_profiles
  lake_depth = 18.0        ! initial lake depth (m)
  num_depths = 3            ! number of profile points
  the_depths = 0, 5, 18    ! depths (m from surface)
  the_temps  = 15, 8, 4    ! temperatures (deg C)
  the_sals   = 0, 0, 0     ! salinity (psu)
  num_wq_vars = 0           ! WQ variables (if AED2 enabled)
  wq_names   = ''
  wq_init_vals = 0
/
```

**Initialization strategies**:
1. **Uniform temperature**: Use mean annual air temperature for well-mixed initial state (best for cold-start in spring/autumn)
2. **Stratified**: Top = summer air temp, bottom = 4 deg C (near maximum density), linear interpolation
3. **Literature/observed**: Published profiles for well-studied lakes
4. **Spinup**: Run 1-2 years with repeated forcing as spinup, discard first year

**Recommended approach**: Start with a 2-year spinup using the first year's forcing repeated. The Lagrangian layer scheme adapts quickly (typically stabilizes within 1-2 months for thermal structure).

### s6_namelist: GLM Namelist Generation

**Purpose**: Assemble glm3.nml from all upstream outputs.

**Namelist blocks** (13 blocks in glm3.nml):

| Block | Key Parameters | Source |
|-------|---------------|--------|
| `&glm_setup` | sim_name, max_layers (500), min/max_layer_thick (0.15/0.5 m), density_model (1) | Defaults + config |
| `&mixing` | surface_mixing (1), coef_mix_conv (0.2), coef_wind_stir (0.402), coef_mix_shear (0.2), coef_mix_turb (0.51), coef_mix_KH (0.3), deep_mixing (2), coef_mix_hyp (0.5) | Defaults (calibratable) |
| `&morphometry` | lake_name, latitude, longitude, bsn_len, bsn_wid, crest_elev, bsn_vals, H[], A[] | s1_lake_identification |
| `&time` | timefmt (3), start, stop, dt (3600), timezone | s0_config |
| `&output` | out_dir, out_fn, nsave (24), csv_lake_fname | Defaults + config |
| `&init_profiles` | lake_depth, num_depths, the_depths, the_temps, the_sals | s5_init_profiles |
| `&meteorology` | met_sw (.true.), lw_type ('LW_IN'), meteo_fl, wind_factor, sw_factor, rain_factor, ce, ch, cd | s2_met_forcing |
| `&bird_model` | AP, Oz, WatVap, AOD500, AOD380, Albedo | Defaults (for clear-sky radiation) |
| `&light` | light_mode (0), Kw (light extinction), n_bands, energy_frac | Defaults (calibratable Kw) |
| `&inflow` | num_inflows, names_of_strms, inflow_fl, inflow_varnum, subm_flag, strm_hf_angle, strmbd_slope, strmbd_drag | s3_inflow |
| `&outflow` | num_outlet, outl_elvs, outflow_fl, outflow_factor, crest_width, crest_factor, flt_off_sw | s4_outflow |
| `&sediment` | sed_heat_Ksoil (2.0), sed_temp_depth (0.2), sed_temp_mean, sed_temp_amplitude, sed_temp_peak_doy, benthic_mode, n_zones | Defaults + latitude-adjusted |
| `&snowice` | snow_albedo_factor, snow_rho_max, snow_rho_min | Defaults (important for northern lakes) |

**Key calibration parameters** (in priority order):

| Parameter | Block | Range | Controls | Sensitivity |
|-----------|-------|-------|----------|-------------|
| Kw | light | 0.1 - 5.0 m^-1 | Light extinction / thermocline depth | HIGH |
| coef_wind_stir | mixing | 0.1 - 1.0 | Surface mixed layer depth | HIGH |
| coef_mix_hyp | mixing | 0.1 - 1.0 | Deep mixing rate | MEDIUM |
| wind_factor | meteorology | 0.5 - 2.0 | Wind speed scaling | MEDIUM |
| sw_factor | meteorology | 0.8 - 1.2 | Solar radiation scaling | MEDIUM |
| ce, ch | meteorology | 0.001 - 0.003 | Evaporation / sensible heat | MEDIUM |
| sed_temp_mean | sediment | 2 - 15 deg C | Sediment heat flux | LOW |
| coef_mix_conv | mixing | 0.1 - 0.5 | Convective mixing | LOW |

### s7_aed_config: AED2 Configuration (Optional)

**Purpose**: Configure the AED2 water quality library.

**Files**:
- `aed2.nml` — master AED configuration (which modules to enable)
- `aed2_phyto_pars.nml` — phytoplankton parameters (if phytoplankton module enabled)
- `aed2_zoop_pars.nml` — zooplankton parameters (if zooplankton module enabled)

**AED2 modules** (enable/disable in aed2.nml):

| Module | Variables | Use Case |
|--------|----------|----------|
| `aed_sedflux` | Sediment oxygen demand, nutrient release | Always recommended |
| `aed_oxygen` | DO, SOD, atmospheric exchange | Water quality basics |
| `aed_carbon` | DIC, DOC, POC, pH, alkalinity | Carbon cycle |
| `aed_silica` | RSi, DSi | Diatom modeling |
| `aed_nitrogen` | NO3, NH4, DON, PON | Nutrient loading |
| `aed_phosphorus` | PO4, DOP, POP | Eutrophication |
| `aed_organic_matter` | DOC_labile, DOC_refractory, POC, DON, DOP | Decomposition |
| `aed_phytoplankton` | Up to 7 phytoplankton groups | Algal blooms |
| `aed_zooplankton` | Zooplankton grazing | Food web |
| `aed_totals` | TN, TP, TOC, TSS | Summary variables |

**Suggested default for HydroCraft**: Enable `aed_oxygen` + `aed_nitrogen` + `aed_phosphorus` + `aed_organic_matter` + `aed_sedflux` + `aed_totals`. Skip phytoplankton and zooplankton for initial deployment (complex parameterization).

### s8_execution: GLM Execution

**Command**:
```bash
cd <run_dir>
glm --nml glm3.nml
```

GLM reads `glm3.nml` from the current directory (or specified path). It is single-threaded (no MPI). Typical runtime:

| Lake size | Simulation period | Timestep | Expected runtime |
|-----------|------------------|----------|-----------------|
| Small (< 1 km^2) | 10 years | 1 hour | 1-5 minutes |
| Medium (1-100 km^2) | 10 years | 1 hour | 5-15 minutes |
| Large (> 100 km^2) | 10 years | 1 hour | 10-30 minutes |

Runtime scales linearly with simulation duration and number of layers. AED2 adds ~2-5x overhead depending on number of WQ modules enabled.

**Output files**:
- `output/output.nc` — Full 2D (time x depth) NetCDF with temperature, salinity, density, and all WQ variables
- `output/lake.csv` — Lake-integrated time series (surface temp, bottom temp, lake level, ice thickness, evaporation, overflow, etc.)
- `output/WQ_*.csv` — Point water quality time series (if configured)
- `output/outlet_*.csv` — Outflow properties time series (flow, temp, salinity, WQ)
- `output/overflow.csv` — Overflow/spillway events

### s9_output_analysis: Output Analysis

**Key output variables to extract and visualize**:

1. **Temperature heatmap**: Depth vs. time contour plot of water temperature — the signature GLM output
2. **Surface/bottom temperature time series**: Stratification onset/breakdown detection
3. **Ice cover duration**: Ice-on date, ice-off date, maximum ice thickness
4. **Thermocline depth**: Seasonal variation of the thermocline
5. **Lake level**: Water balance validation
6. **Schmidt stability**: Resistance to mixing (computed from temperature profile)
7. **DO profiles** (if AED2): Hypolimnetic anoxia detection
8. **Nutrient concentrations** (if AED2): Surface/bottom N, P time series

**Validation metrics**:
- RMSE of temperature at observed depths
- Bias in thermocline depth
- Ice-on/ice-off date accuracy
- Mean absolute error of surface temperature
- Nash-Sutcliffe efficiency for temperature at multiple depths

### s10_coupling: Downstream Coupling

**GLM outputs that feed other HydroCraft models**:

| Source (GLM) | Target Model | Variable | Transformation |
|-------------|-------------|----------|----------------|
| Outflow temperature | CaMa-Flood | Water temperature at release point | outlet_*.csv TEMP column |
| Outflow discharge | CaMa-Flood | Release flow (replaces natural routing) | outlet_*.csv FLOW column |
| Outflow nutrients | SWAT+ / RZWQM2 | N, P loading downstream | outlet_*.csv WQ columns |
| Epilimnion temperature | LDNDC | Lake surface temperature for GHG exchange | lake.csv surface_temp |
| Lake level | Pywr | Reservoir storage state | lake.csv lake_level |

---

## 6. Tools to Build

### Tool Inventory (13 tools, estimated ~4,500 lines)

| # | Tool ID | Stage | Script Path | Est. Lines | Purpose |
|---|---------|-------|-------------|-----------|---------|
| 1 | `lookup_hydrolakes` | s1 | `tools/s1_lake_identification/lookup_hydrolakes.py` | 350 | Find lake in HydroLAKES by name or coordinates, extract morphometric parameters |
| 2 | `build_morphometry` | s1 | `tools/s1_lake_identification/build_morphometry.py` | 250 | Construct depth-area hypsographic curve from HydroLAKES attributes or user-provided bathymetry |
| 3 | `convert_met_to_glm` | s2 | `tools/s2_met_forcing/convert_met_to_glm.py` | 500 | Convert CMFD/MSWX/NASA POWER forcing to GLM meteorological CSV (unit conversions: VP->RH, mm->m/day) |
| 4 | `convert_inflow_to_glm` | s3 | `tools/s3_inflow/convert_inflow_to_glm.py` | 400 | Convert CaMa-Flood/VIC discharge to GLM inflow CSV; estimate inflow temperature from air temperature |
| 5 | `configure_outflow` | s4 | `tools/s4_outflow/configure_outflow.py` | 300 | Generate outflow CSV and parameters for dam/natural outlet; support scheduled releases |
| 6 | `build_init_profiles` | s5 | `tools/s5_init_profiles/build_init_profiles.py` | 200 | Generate initial temperature/salinity/WQ profiles from climatology or user data |
| 7 | `generate_glm_nml` | s6 | `tools/s6_namelist/generate_glm_nml.py` | 600 | Assemble glm3.nml from upstream outputs; validate parameter ranges; handle all 13 namelist blocks |
| 8 | `generate_aed_config` | s7 | `tools/s7_aed_config/generate_aed_config.py` | 500 | Generate aed2.nml and phyto/zoop parameter files; module selection based on data availability |
| 9 | `run_glm` | s8 | `tools/s8_execution/run_glm.py` | 250 | Execute GLM binary with preflight checks, timeout, log capture, success verification |
| 10 | `parse_glm_output` | s9 | `tools/s9_output_analysis/parse_glm_output.py` | 400 | Parse output.nc and lake.csv; extract temperature profiles, ice, lake level; compute derived metrics |
| 11 | `plot_glm_results` | s9 | `tools/s9_output_analysis/plot_glm_results.py` | 500 | Generate temperature heatmap, surface/bottom temp, ice, lake level plots |
| 12 | `glm_to_cama_outflow` | s10 | `tools/s10_coupling/glm_to_cama_outflow.py` | 300 | Convert GLM outflow to CaMa-Flood lateral inflow at downstream grid cell |
| 13 | `calibrate_glm` | s9 | `tools/s9_output_analysis/calibrate_glm.py` | 450 | GLUE-style calibration: sample Kw, coef_wind_stir, coef_mix_hyp, wind_factor; compare to observed temperature |

**Total**: 13 tools, ~4,500 lines estimated.

### Tool Details for Critical Tools

#### `lookup_hydrolakes` (Tool #1)

```python
# Input: lake_name or (lat, lon) + search_radius_km
# Process:
#   1. Load HydroLAKES shapefile (1.4M polygons — use spatial index)
#   2. If name: fuzzy match on Lake_name column
#   3. If coords: buffer point by search_radius, spatial intersect
#   4. If reservoir: also check GRanD for dam-specific attributes
#   5. Return: Hylak_id, Lake_name, Lake_area, Depth_avg, Vol_total,
#              Shore_len, Res_time, Elevation, Pour_lat, Pour_lon, Lake_type
# Output: JSON with all morphometric parameters
# Edge cases:
#   - Multiple matches within radius — return all, sorted by distance
#   - No match — suggest nearby lakes, or fall back to user-provided morphometry
#   - Very large shapefile — use rtree/geopandas spatial index for speed
```

#### `convert_met_to_glm` (Tool #3)

```python
# Input: forcing_dir (CMFD/MSWX), grid_nc (VIC basin grid), lake_lat, lake_lon,
#        start_date, end_date, output_path
# Process:
#   1. Find the forcing grid cell closest to lake_lat/lake_lon
#   2. Extract 7 variables for the simulation period
#   3. Unit conversions (CRITICAL):
#      - VP (kPa) -> RH (%): RH = 100 * VP / (0.6108 * exp(17.27*T/(T+237.3)))
#      - PRECIP (mm/3hr) -> Rain (m/day): * 8 / 1000
#      - Partition rain/snow by air temperature (threshold 0-2 deg C)
#   4. Temporal resampling: 3-hourly to hourly (linear interpolation for T, RH, Wind;
#      step for SW, Rain)
#   5. Write CSV with GLM header format
# Output: bcs/met_hourly.csv
# Silent error traps:
#   - Rain in mm/day instead of m/day (lake floods — 1000x error)
#   - RH as fraction instead of percentage (extreme evaporation)
#   - SW radiation negative at night (should be 0, not negative)
#   - Missing longwave (GLM can compute from cloud cover, but needs correct lw_type)
```

#### `generate_glm_nml` (Tool #7)

```python
# Input: morphometry.json, met_file_path, inflow configs, outflow configs,
#        init_profiles, simulation period, AED2 flag
# Process:
#   1. Build all 13 namelist blocks from inputs
#   2. Validate parameter ranges (e.g., dt > 0, max_layers > 10, Kw > 0)
#   3. Check path existence for all referenced files (meteo_fl, inflow_fl, outflow_fl)
#   4. Adjust sediment temperature based on latitude:
#      - Tropical: sed_temp_mean ~ 20-25 deg C
#      - Temperate: sed_temp_mean ~ 5-10 deg C
#      - Boreal/Arctic: sed_temp_mean ~ 2-5 deg C
#   5. Write Fortran namelist format (& ... /)
# Output: glm3.nml
# Critical: Fortran namelist format is strict:
#   - Strings must be single-quoted
#   - Booleans must be .true. or .false.
#   - Arrays comma-separated
#   - Each block starts with &block_name and ends with /
```

---

## 7. Skill Documents to Write

| # | Document ID | Stage | Path | Key Content |
|---|------------|-------|------|-------------|
| 1 | sd_s0 | s0_config | `docs/s0_configuration_skill.md` | Lake selection criteria, period constraints, forcing dataset selection for lakes |
| 2 | sd_s1 | s1_lake_identification | `docs/s1_lake_identification_skill.md` | HydroLAKES search strategy, morphometry construction, depth-area curve validation |
| 3 | sd_s2 | s2_met_forcing | `docs/s2_met_forcing_skill.md` | Unit conversion table (VP->RH, mm->m/day), temporal resampling, forcing quality checks |
| 4 | sd_s3 | s3_inflow | `docs/s3_inflow_skill.md` | Inflow temperature estimation, density insertion physics, multiple inflows |
| 5 | sd_s4 | s4_outflow | `docs/s4_outflow_skill.md` | Dam operation modes, withdrawal depth effects on downstream temperature |
| 6 | sd_s5 | s5_init_profiles | `docs/s5_init_profiles_skill.md` | Spinup strategy, isothermal vs stratified initialization, WQ initial conditions |
| 7 | sd_s6 | s6_namelist | `docs/s6_namelist_skill.md` | All 13 blocks documented, parameter ranges, Fortran namelist format rules |
| 8 | sd_s7 | s7_aed_config | `docs/s7_aed_config_skill.md` | AED2 module selection, default parameters, coupling with GLM |
| 9 | sd_s8 | s8_execution | `docs/s8_execution_skill.md` | Runtime expectations, error messages, convergence issues, restart files |
| 10 | sd_s9 | s9_output | `docs/s9_output_analysis_skill.md` | Output.nc structure, lake.csv columns, validation metrics, visualization |
| 11 | sd_s10 | s10_coupling | `docs/s10_coupling_skill.md` | GLM-CaMa coupling, GLM-SWAT+ coupling, temperature propagation downstream |
| 12 | sd_calib | calibration | `docs/calibration_guide.md` | Calibration parameters by priority, GLUE methodology, observed data requirements |

**Total**: 12 skill documents, estimated ~8,000 words.

---

## 8. Diagnostic Triplets (Anticipated)

### By Failure Domain

#### Unit Conversion (HIGHEST PRIORITY — Silent Errors)

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_001 | s2_met | Lake level rises continuously, overflow every day | Rain in mm/day instead of m/day (1000x too much) | Divide rain by 1000 in convert_met_to_glm.py | silent |
| dt_002 | s2_met | Lake dries up, extreme evaporation | RelHum as fraction (0-1) instead of percentage (0-100) | Multiply RH by 100 | silent |
| dt_003 | s2_met | Negative SW radiation values in forcing CSV | Night-time SW not clipped to 0 | `max(0, SW)` after interpolation | silent |
| dt_004 | s3_inflow | Inflow temperature always 0 or missing | Temperature column missing from inflow CSV | Estimate from air temperature if not available | degraded |
| dt_005 | s6_namelist | Fortran read error on namelist | String values use double quotes instead of single quotes | Use single quotes in Fortran namelist format | fatal |

#### Parameter Format

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_006 | s1_morph | GLM crashes at startup with "layer thickness" error | H/A arrays not monotonically increasing | Sort H[] ascending, ensure A[] corresponds | fatal |
| dt_007 | s1_morph | Lake volume wrong, unrealistic depth | Depth-area curve has too few points (< 5) | Interpolate to at least 10-15 depth levels | degraded |
| dt_008 | s6_namelist | `bsn_vals` does not match length of H/A arrays | Manual count error | Auto-compute bsn_vals from array length in generate_glm_nml.py | fatal |
| dt_009 | s5_init | `lake_depth` exceeds morphometry max depth | init_profiles depth > max(H) - min(H) | Clip lake_depth to morphometry range | fatal |
| dt_010 | s6_namelist | `num_inflows` is 0 but inflow files configured | Inconsistency between inflow count and file list | Auto-set num_inflows from number of inflow files | silent |

#### Path Resolution

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_011 | s8_exec | "Unable to open meteo file" | meteo_fl path in namelist is relative but GLM run from wrong directory | Use absolute paths or ensure cd to run directory | fatal |
| dt_012 | s8_exec | "Unable to open inflow file" | inflow_fl path mismatch | Check all file paths in namelist exist before execution | fatal |

#### Runtime Errors

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_013 | s8_exec | GLM crashes with NaN in temperature | Extremely large wind speed or zero dt | Check forcing for outliers; ensure dt >= 60 | fatal |
| dt_014 | s8_exec | Ice model produces unrealistic thickness (>5m) | Snow accumulation without melt in warm climate | Disable snow-ice for tropical lakes (lat < 23) | degraded |
| dt_015 | s8_exec | "Layer merge error" or infinite loop | max_layer_thick too small relative to lake depth | Increase max_layer_thick; reduce max_layers if needed | fatal |

#### Dependency Mismatch

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_016 | s3_inflow | Inflow timing offset — flow arrives 1 day early/late | Timezone mismatch between forcing and inflow data | Ensure all CSV timestamps use the same timezone as GLM `timezone` parameter | silent |
| dt_017 | s10_coupling | CaMa-Flood discharge inconsistent with GLM inflow | CaMa grid cell does not match the lake inlet | Verify spatial alignment of CaMa output point with GLM inflow location | silent |
| dt_018 | s9_output | Temperature heatmap shows artifacts at boundaries | Output nsave too large — misses diurnal cycle | Set nsave to capture at least 4 outputs per day for thermal analysis | degraded |

#### Silent Errors (Model Runs, Results Wrong)

| ID | Stage | Symptom | Root Cause | Remedy | Severity |
|----|-------|---------|------------|--------|----------|
| dt_019 | s1_morph | Stratification never develops in deep lake | Kw too high (>3) — all heat absorbed near surface, no deep warming | Literature review for Kw; start with 0.3-1.0 for clear lakes, 1-3 for turbid | silent |
| dt_020 | s2_met | Summer temperatures too warm by 3-5 deg C | LongWave radiation double-counted (both computed internally and provided in forcing) | Set lw_type consistently: 'LW_IN' if forcing has LW, 'LW_CC' if only cloud cover | silent |
| dt_021 | s6_namelist | Mixing too strong — no stratification | coef_wind_stir too high for sheltered lake | Reduce wind_factor or coef_wind_stir for small/sheltered lakes | silent |
| dt_022 | s3_inflow | Inflow causes artificial cold/warm layer at wrong depth | Inflow salinity set to non-zero when lake is freshwater | Set inflow salinity to 0 for freshwater lakes | silent |

**Total**: 22 anticipated diagnostic triplets across 6 failure domains.

---

## 9. Coupling Points with HydroCraft

### Coupling Matrix

| # | Coupling ID | Source Model | Target Model | Variable | Direction | Transformation |
|---|------------|-------------|-------------|----------|-----------|----------------|
| 1 | c_glm_01 | CaMa-Flood | GLM | Discharge at lake inlet | CaMa -> GLM | Extract outflw at upstream grid cell; convert to inflow CSV format |
| 2 | c_glm_02 | VIC | GLM | Runoff + baseflow from local catchment | VIC -> GLM | Sum runoff+baseflow from grid cells in lake's immediate catchment |
| 3 | c_glm_03 | VIC | GLM | Meteorological forcing | VIC -> GLM | Same forcing files, converted to GLM CSV format (unit changes) |
| 4 | c_glm_04 | GLM | CaMa-Flood | Outflow discharge | GLM -> CaMa | GLM outlet_*.csv FLOW -> CaMa lateral inflow at downstream cell |
| 5 | c_glm_05 | GLM | CaMa-Flood | Outflow temperature | GLM -> CaMa | GLM outlet_*.csv TEMP -> water temperature at release point |
| 6 | c_glm_06 | GLM | LDNDC | Lake surface temperature | GLM -> LDNDC | lake.csv surface_temp -> boundary condition for riparian GHG exchange |
| 7 | c_glm_07 | GLM | SWAT+ | Outflow nutrients (N, P) | GLM -> SWAT+ | outlet_*.csv WQ columns -> SWAT+ point source input |
| 8 | c_glm_08 | SWAT+ | GLM | Nutrient loading from watershed | SWAT+ -> GLM | SWAT+ channel output N/P -> GLM inflow WQ variables |
| 9 | c_glm_09 | Pywr | GLM | Reservoir release schedule | Pywr -> GLM | Pywr optimized releases -> GLM outflow CSV time series |
| 10 | c_glm_10 | GLM | Pywr | Lake storage/level state | GLM -> Pywr | GLM lake.csv lake_level -> Pywr reservoir state update |
| 11 | c_glm_11 | CMIP6 | GLM | Future climate forcing | CMIP6 -> GLM | Delta-change on met forcing -> GLM future projections |
| 12 | c_glm_12 | OGGM | GLM | Glacier-fed lake inflow | OGGM -> GLM | OGGM meltwater discharge -> GLM cold inflow stream |

### Priority Couplings for Initial Implementation

**Phase 1** (essential, build first):
- c_glm_01: CaMa-Flood -> GLM inflow (makes GLM useful in catchment simulations)
- c_glm_03: VIC forcing -> GLM meteorology (shared forcing pipeline)
- c_glm_04: GLM outflow -> CaMa-Flood downstream (closes the loop)

**Phase 2** (high value):
- c_glm_08: SWAT+ nutrient loading -> GLM (eutrophication analysis)
- c_glm_07: GLM nutrients -> SWAT+ (downstream water quality)
- c_glm_11: CMIP6 -> GLM (climate change impacts on lakes)

**Phase 3** (advanced):
- c_glm_09/10: Pywr <-> GLM (reservoir optimization)
- c_glm_06: GLM -> LDNDC (lake-atmosphere GHG exchange)
- c_glm_12: OGGM -> GLM (glacier-fed lakes)

---

## 10. Data Requirements & Global Databases

### Required Data and Sources

| Data | Source | Coverage | Local Path (Planned) | Status |
|------|--------|----------|---------------------|--------|
| Lake morphometry | HydroLAKES v10 | Global, 1.4M lakes >= 0.1 km^2 | `data/lakes/HydroLAKES_polys_v10.shp` | **TO DOWNLOAD** (~2.5 GB) |
| Reservoir attributes | GRanD v1.3 | Global, ~7,300 large dams | `data/lakes/GRanD_v1.3.shp` | **TO DOWNLOAD** (~50 MB) |
| Meteorological forcing | CMFD / MSWX | China / Global | Already available | Available |
| River inflow | CaMa-Flood / VIC output | Simulation-dependent | From HydroCraft pipeline | Available |
| Observed lake temperature | GLEON / published | Lake-specific | `data/obs/lakes/` | Per-lake basis |
| GLM example datasets | glm-aed repo | 5 reference lakes | `model/glm/examples/` | **TO DOWNLOAD** |
| Water table depth | Reinecke et al. | Global, 5 arcmin | Already available (MODFLOW) | Available |

### HydroLAKES Download Plan

```bash
# Option 1: Direct download
wget https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip
unzip -d data/lakes/ HydroLAKES_polys_v10_shp.zip

# Option 2: From HydroSHEDS
# https://www.hydrosheds.org/products/hydrolakes
```

**Spatial index**: Build a geopandas-compatible spatial index on first load for fast point-in-polygon queries. Cache the index at `data/lakes/HydroLAKES_polys_v10.sindex`.

---

## 11. Validation Plan

### Tier 1: Reference Example (Day 1)

**Lake**: Sparkling Lake (Wisconsin, USA) — included in glm-aed examples
- Already has calibrated glm3.nml, met forcing, and reference output
- Purpose: Verify binary works, output matches published results
- Validation: Compare output.nc temperature profiles to example reference

### Tier 2: Chinese Reservoir (Week 1)

**Candidate**: Miyun Reservoir (密云水库), Beijing
- **Why**: Close to the Chao River (Chaohe) basin already simulated in HydroCraft. Miyun is at the downstream end of the Chao + Bai rivers.
- **Location**: 40.48N, 116.97E
- **Area**: ~188 km^2 (varies with level)
- **Max depth**: ~60 m (near dam)
- **In HydroLAKES**: Yes (Hylak_id to be confirmed)
- **Available data**: Some published temperature profiles (Beijing Water Authority), hydrological yearbooks
- **Coupling test**: CaMa-Flood Chaohe discharge -> GLM Miyun inflow -> GLM outflow -> downstream

**Alternative candidates** (if Miyun data unavailable):
1. **Taihu (太湖)**: Large shallow lake (2,338 km^2, mean depth 1.9 m), extensive observed data, eutrophication focus. Good for AED2 WQ validation.
2. **Danjiangkou (丹江口水库)**: Source of South-to-North Water Transfer, 745 km^2, ~80 m deep. Critical for water quality.
3. **Three Gorges (三峡水库)**: 1,084 km^2, ~175 m deep. The most important Chinese reservoir but complex (cascade operation).

### Tier 3: Global Validation (Week 2-3)

**Lake Ammersee** (Germany) — well-published GLM validation
- Hipsey et al. (2019) paper includes Ammersee results
- Deep, monomictic lake with good long-term observed data
- Tests ice model (winters can freeze)

### Validation Protocol

For each validation lake:
1. Run GLM with default parameters
2. Compare simulated vs observed surface temperature (RMSE, bias)
3. Compare simulated vs observed thermocline depth (if available)
4. Compare simulated vs observed ice-on/ice-off dates (for northern lakes)
5. Calibrate (Kw, coef_wind_stir, wind_factor) using GLUE
6. Report calibrated RMSE and parameter values
7. Write results to shared findings (basin_context.yaml)

---

## 12. Estimated Effort

### Phase 1: Installation & Verification (0.5 days)

| Task | Time |
|------|------|
| Download and install GLM binary (.deb) | 15 min |
| Download HydroLAKES shapefile | 30 min |
| Clone glm-aed examples | 10 min |
| Run Sparkling Lake example, verify output | 30 min |
| **Subtotal** | **~1.5 hours** |

### Phase 2: Core Pipeline Tools (2-3 days)

| Task | Time |
|------|------|
| Tool #1: lookup_hydrolakes | 3 hours |
| Tool #2: build_morphometry | 2 hours |
| Tool #3: convert_met_to_glm | 4 hours |
| Tool #4: convert_inflow_to_glm | 3 hours |
| Tool #5: configure_outflow | 2 hours |
| Tool #6: build_init_profiles | 1.5 hours |
| Tool #7: generate_glm_nml | 4 hours |
| Tool #9: run_glm | 2 hours |
| Tool #10: parse_glm_output | 3 hours |
| **Subtotal** | **~24 hours** |

### Phase 3: Validation & Calibration (1-2 days)

| Task | Time |
|------|------|
| Miyun Reservoir end-to-end test | 6 hours |
| Tool #11: plot_glm_results | 3 hours |
| Tool #13: calibrate_glm | 4 hours |
| Fix bugs discovered during validation | 4 hours |
| **Subtotal** | **~17 hours** |

### Phase 4: AED2 & Coupling (1-2 days)

| Task | Time |
|------|------|
| Tool #8: generate_aed_config | 4 hours |
| Tool #12: glm_to_cama_outflow | 3 hours |
| AED2 validation (Taihu nutrients) | 4 hours |
| CaMa-Flood <-> GLM coupling test | 4 hours |
| **Subtotal** | **~15 hours** |

### Phase 5: Documentation & Diagnostics (1 day)

| Task | Time |
|------|------|
| 12 skill documents | 6 hours |
| 22 diagnostic triplets | 3 hours |
| SKILL.md + knowledge_infrastructure.yaml | 2 hours |
| **Subtotal** | **~11 hours** |

### Total: 5-8 working days

---

## 13. Priority & Dependencies

### Dependencies on Existing HydroCraft Components

| Dependency | Component | Status | Notes |
|-----------|-----------|--------|-------|
| VIC forcing pipeline | `skills/vic-auto-run/s2_forcing/` | Available | Re-use for GLM met forcing (with unit conversion) |
| CaMa-Flood output | `skills/cama-flood-run/` | Available | Source of inflow discharge |
| Basin delineation | `hydrobasin/` | Available | For lake catchment delineation |
| HWSD soil data | `data/soil/HWSD_RASTER/` | Available | Not directly needed by GLM but useful for sediment params |
| Plotting infrastructure | `skills/plot/` | Available | Add GLM-specific plot scripts |
| Shared findings | `tools/write_findings.py` | Available | For multi-model coordination |

### Dependencies on External Downloads

| Item | Size | Source | Priority |
|------|------|--------|----------|
| GLM binary (.deb) | ~20 MB | GitHub glm-aed/binaries/ubuntu | CRITICAL |
| HydroLAKES shapefile | ~2.5 GB | hydrosheds.org | CRITICAL |
| glm-aed examples | ~50 MB | GitHub glm-aed/glm-examples | HIGH |
| GRanD v1.3 shapefile | ~50 MB | globaldamwatch.org | MEDIUM |

### Implementation Priority Order

1. **Install GLM binary** — verify it runs on the server
2. **Download HydroLAKES** — enable lake lookup for any location worldwide
3. **Build core tools** (#1, #2, #3, #7, #9, #10) — minimum viable lake simulation
4. **Validate on Sparkling Lake** — verify against published results
5. **Build inflow/outflow tools** (#4, #5) — enable CaMa-Flood coupling
6. **Validate on Miyun Reservoir** — first Chinese reservoir, coupled with existing Chaohe run
7. **Build calibration tool** (#13) — tune to observed temperature
8. **Build AED2 tools** (#8) — water quality capability
9. **Build coupling tools** (#12) — close the loop with CaMa-Flood
10. **Write skill documents and triplets** — complete the KI package

---

## 14. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| .deb binary incompatible with server Ubuntu | Low | Medium | Compile from source as fallback |
| HydroLAKES missing small Chinese reservoirs | Medium | Medium | Supplement with China reservoir database; allow user-provided morphometry |
| Inflow temperature estimation too crude | Medium | Low | Literature review for T_inflow = f(T_air) regressions by climate zone |
| AED2 parameterization too complex for automation | High | Medium | Start with "default AED2" profile; defer full parameterization to Phase 2 |
| Observed lake temperature data scarce for Chinese lakes | High | Medium | Use Landsat/MODIS surface temperature as validation proxy |
| GLM single-threaded — slow for multi-lake batch runs | Low | Low | Each lake runs independently; parallelize across lakes |

---

## 15. File Structure (Target)

```
models/GLM/
  knowledge_infrastructure/
    DISSECTION_PLAN.md              # This file
    SKILL.md                        # Agent entry point (after dissection)
    knowledge_infrastructure.yaml   # Schema-compliant package definition
    workflow/
      pipeline.drawio              # Visual pipeline diagram
      workflow.md                  # Agent-readable workflow
    tools/
      s1_lake_identification/
        lookup_hydrolakes.py
        build_morphometry.py
      s2_met_forcing/
        convert_met_to_glm.py
      s3_inflow/
        convert_inflow_to_glm.py
      s4_outflow/
        configure_outflow.py
      s5_init_profiles/
        build_init_profiles.py
      s6_namelist/
        generate_glm_nml.py
      s7_aed_config/
        generate_aed_config.py
      s8_execution/
        run_glm.py
      s9_output_analysis/
        parse_glm_output.py
        plot_glm_results.py
        calibrate_glm.py
      s10_coupling/
        glm_to_cama_outflow.py
    docs/
      s0_configuration_skill.md
      s1_lake_identification_skill.md
      s2_met_forcing_skill.md
      s3_inflow_skill.md
      s4_outflow_skill.md
      s5_init_profiles_skill.md
      s6_namelist_skill.md
      s7_aed_config_skill.md
      s8_execution_skill.md
      s9_output_analysis_skill.md
      s10_coupling_skill.md
      calibration_guide.md
    diagnostics/
      triplets.yaml                # 22+ diagnostic triplets
      error_log.yaml               # Errors from real runs (populated during validation)

model/glm/
  bin/glm                          # GLM-AED binary
  examples/                        # Reference datasets

data/lakes/
  HydroLAKES_polys_v10.shp        # Global lake database (+ .dbf, .shx, .prj)
  GRanD_v1.3.shp                  # Global reservoir/dam database
```

---

## 16. Integration with HydroCraft Platform

### CLAUDE.md Updates Required

After GLM is validated, add to the CLAUDE.md:

```markdown
| **Lake/Reservoir** | GLM 3.3.x + AED2 | 1D thermal stratification, mixing, ice, water quality |
```

Add to the Supported Models table, Global Databases table (HydroLAKES), and Platform Numbers.

### New Skill Entry

```markdown
| glm-lake-run | GLM lake/reservoir simulation (thermal + optional WQ) |
```

### New Coupling Entries

```markdown
| c_glm_01 | CaMa-Flood discharge -> GLM lake inflow |
| c_glm_04 | GLM outflow -> CaMa-Flood downstream routing |
```

### Web UI Integration

Add GLM to the model selection menu in `Hydrocraft/hydrocraft-web/`. When a user selects a basin containing a major lake/reservoir (detectable from HydroLAKES intersection with basin shapefile), offer: "This basin contains [Lake X] (area: Y km^2, depth: Z m). Would you like to simulate lake thermodynamics with GLM?"

---

## Appendix A: GLM glm3.nml Complete Reference

Based on Sparkling Lake example (glm-aed repository):

```fortran
&glm_setup
  sim_name = 'GLMSimulation'
  max_layers = 500
  min_layer_vol = 0.5
  min_layer_thick = 0.15
  max_layer_thick = 0.5
  density_model = 1
  non_avg = .true.
/

&mixing
  surface_mixing = 1
  coef_mix_conv = 0.2
  coef_wind_stir = 0.402
  coef_mix_shear = 0.2
  coef_mix_turb = 0.51
  coef_mix_KH = 0.3
  deep_mixing = 2
  coef_mix_hyp = 0.5
  diff = 0.0
/

&morphometry
  lake_name = 'ExampleLake'
  latitude = 40.0
  longitude = 116.0
  bsn_len = 1000.0
  bsn_wid = 500.0
  crest_elev = 100.0
  bsn_vals = 10
  H = 80, 82, 84, 86, 88, 90, 92, 94, 96, 98, 100
  A = 0, 1000, 5000, 15000, 30000, 50000, 80000, 120000, 170000, 220000, 280000
/

&time
  timefmt = 3
  start = '2000-01-01 00:00:00'
  stop = '2010-12-31 23:00:00'
  dt = 3600
  timezone = 8
/

&output
  out_dir = 'output'
  out_fn = 'output'
  nsave = 24
  csv_lake_fname = 'lake'
/

&init_profiles
  lake_depth = 20.0
  num_depths = 3
  the_depths = 0, 10, 20
  the_temps = 15, 8, 4
  the_sals = 0, 0, 0
/

&meteorology
  met_sw = .true.
  lw_type = 'LW_IN'
  rain_sw = .false.
  atm_stab = 0
  catchrain = .false.
  rad_mode = 1
  albedo_mode = 1
  cloud_mode = 4
  subdaily = .true.
  meteo_fl = 'bcs/met_hourly.csv'
  wind_factor = 1.0
  sw_factor = 1.0
  lw_factor = 1.0
  at_factor = 1.0
  rh_factor = 1.0
  rain_factor = 1.0
  ce = 0.0013
  ch = 0.0014
  cd = 0.0013
/

&light
  light_mode = 0
  Kw = 0.5
/

&bird_model
  AP = 973
  Oz = 0.279
  WatVap = 1.1
  AOD500 = 0.033
  AOD380 = 0.038
  Albedo = 0.2
/

&inflow
  num_inflows = 1
  names_of_strms = 'River1'
  subm_flag = .false.
  strm_hf_angle = 65.0
  strmbd_slope = 2.0
  strmbd_drag = 0.016
  inflow_factor = 1.0
  inflow_fl = 'bcs/inflow_1.csv'
  inflow_varnum = 3
  inflow_vars = 'FLOW','TEMP','SALT'
/

&outflow
  num_outlet = 1
  flt_off_sw = .false.
  outl_elvs = 90.0
  bsn_len_outl = 100
  bsn_wid_outl = 50
  outflow_fl = 'bcs/outflow.csv'
  outflow_factor = 1.0
  crest_width = 100.0
  crest_factor = 0.61
/

&sediment
  sed_heat_Ksoil = 2.0
  sed_temp_depth = 0.2
  sed_temp_mean = 8.0
  sed_temp_amplitude = 6.0
  sed_temp_peak_doy = 242
  benthic_mode = 2
  n_zones = 1
  zone_heights = 20.0
  sed_reflectivity = 0.1
  sed_roughness = 0.01
/

&snowice
  snow_albedo_factor = 1.0
  snow_rho_max = 500
  snow_rho_min = 100
/
```

## Appendix B: GLM Meteorological CSV Example

```csv
time,ShortWave,LongWave,AirTemp,RelHum,WindSpeed,Rain,Snow
2000-01-01 00:00:00,0.0,250.3,-5.2,72.4,3.1,0.0,0.0005
2000-01-01 01:00:00,0.0,249.8,-5.5,73.1,2.8,0.0,0.0
2000-01-01 02:00:00,0.0,248.5,-5.8,74.2,2.5,0.0,0.0
2000-01-01 03:00:00,0.0,247.9,-6.1,75.0,2.3,0.0,0.0
2000-01-01 04:00:00,0.0,247.2,-6.3,75.5,2.1,0.0,0.0
2000-01-01 05:00:00,0.0,246.8,-6.5,76.1,1.9,0.0,0.0
2000-01-01 06:00:00,0.0,246.5,-6.6,76.5,1.8,0.0,0.0
2000-01-01 07:00:00,15.2,248.1,-6.2,75.8,2.0,0.0,0.0
2000-01-01 08:00:00,85.6,252.3,-5.1,73.2,2.5,0.0,0.0
```

Units: ShortWave (W/m^2), LongWave (W/m^2), AirTemp (deg C), RelHum (%), WindSpeed (m/s), Rain (m/day), Snow (m/day)

## Appendix C: GLM Inflow CSV Example

```csv
time,FLOW,TEMP,SALT
2000-01-01 00:00:00,15.3,2.1,0.0
2000-01-02 00:00:00,14.8,1.9,0.0
2000-01-03 00:00:00,16.2,2.3,0.0
```

Units: FLOW (m^3/s), TEMP (deg C), SALT (psu)

## Appendix D: GLM Outflow CSV Example

```csv
time,FLOW
2000-01-01 00:00:00,12.5
2000-01-02 00:00:00,12.5
2000-01-03 00:00:00,13.0
```

Units: FLOW (m^3/s). Negative values not allowed.
