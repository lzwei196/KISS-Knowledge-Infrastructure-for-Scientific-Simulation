---
name: hype-hydrocraft
version: "1.0.0"
model: HYPE v5.35.0
domain: semi-distributed hydrology with integrated nutrient transport
validation_status: production_validated
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

## Data Preparation (use these commands — do NOT write custom data extraction code)

### Lake/reservoir data
```bash
# Generate LakeData.txt from HydroLAKES + GRanD:
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_lakedata.py \
    --geodata [GEODATA] --geoclass [GEOCLASS] --output [OUTPUT] \
    --lat [LAT] --lon [LON] --search_radius_km 100 --update_geodata

# Generate DamData.txt from GRanD:
python KISSPATH_KI_ROOT/HYPE/knowledge_infrastructure/tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata [GEODATA] --output [OUTPUT] \
    --lat [LAT] --lon [LON] --search_radius_km 200
```

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
Then convert to HYPE forcing format using this KI's tool: `tools/s3_forcing_preparation/convert_forcing_to_hype.py`

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# HYPE Knowledge Infrastructure for HydroCraft

## Model Overview

**HYPE (HYdrological Predictions for the Environment)** is a semi-distributed, process-based hydrological and nutrient transport model developed at SMHI (Swedish Meteorological and Hydrological Institute). It operates on a subbasin-SLC (Soil-Land use Class) structure where the landscape is divided into subbasins, each containing fractional areas of soil-landcover combinations.

**Binary**: `KISSPATH_BINARIES/hype/hype` (v5.35.0, compiled from source)
**Source**: `KISSPATH_BINARIES/hype/hype_5_35_0_src/` (38 Fortran 90 files, 93,622 lines)
**Demo**: `KISSPATH_BINARIES/hype/demo/` (3-subbasin test case, validated)

### What Makes HYPE Unique in HydroCraft

| Capability | VIC | mHM | **HYPE** |
|-----------|-----|-----|----------|
| Spatial structure | Grid cells | Grid (L0/L1/L11) | **Subbasins + SLC fractions** |
| Nutrient simulation | No | No | **Yes (N + P cycles)** |
| Lake/reservoir modeling | No | No | **Yes (native, LakeData/DamData)** |
| Parameter type | Per-cell | MPR global | **Per land-use/soil type** |
| Routing topology | External (Lohmann/CaMa) | Internal (MRM) | **Internal (MAINDOWN)** |
| World-Wide setup | No | No | **Yes (WWH)** |
| Data assimilation | No | No | **Yes (built-in ensemble)** |
| Calibration | External | Built-in DDS/SCE | **Built-in DDS/DEMC** |
| Dependencies | NetCDF | NetCDF, LAPACK | **None (pure Fortran 90)** |

### Strategic Value

1. **Integrated water quality**: HYPE simulates nitrogen and phosphorus transport simultaneously with hydrology -- no coupling needed.
2. **World-Wide HYPE (WWH)**: A global setup exists with pre-calibrated parameters, enabling prediction anywhere.
3. **Lake/reservoir support**: Native handling of regulated lakes and dams via LakeData.txt and DamData.txt.
4. **Parameter regionalization**: Parameters are defined per soil type and land use, enabling transfer between basins with similar landscapes.
5. **No dependencies**: Pure Fortran 90, compiles with gfortran in under 60 seconds.

---

## Architecture: Subbasins + SLC

HYPE divides the landscape into **subbasins** connected by a routing network (MAINDOWN topology). Each subbasin contains fractional areas of **SLC (Soil-Land use Class)** combinations:

```
Basin
  |-- Subbasin 1 (area=150 km2)
  |     |-- SLC_1 (forest/till)     60%
  |     |-- SLC_2 (cropland/clay)   30%
  |     |-- SLC_3 (water)           10%
  |-- Subbasin 2 (area=200 km2)
  |     |-- SLC_1                   40%
  |     |-- SLC_2                   50%
  |     |-- SLC_3                   10%
  |-- Subbasin 3 (outlet, area=500 km2)
        |-- SLC_1                   35%
        |-- SLC_2                   45%
        |-- SLC_3                   20%
```

**CRITICAL**: SLC fractions per subbasin MUST sum to 1.0. If they don't, the water balance is wrong but HYPE produces NO warning.

---

## Input File Format Reference

All HYPE input files are **tab-separated text** with `!!` comment lines at the top.

### info.txt (Main configuration)
```
bdate     2005-01-01
cdate     2005-01-01          !! criteria/output start (skip warmup)
edate     2010-12-31
resultdir ./resultdir/        !! trailing slash required
modeldir  ./modelfiles/       !! trailing slash required
forcingdir ./forcingdir/       !! trailing slash required
logdir    ./logdir/            !! trailing slash required
timeoutput variable cout rout snow evap cprc
timeoutput meanperiod 1
modeloption petmodel 1         !! 0=default, 1=Jensen-Haise, 2=Hargreaves, 5=Penman-Monteith
modeloption snowmeltmodel 2    !! 0=degree-day, 2=degree-day with radiation
```

**CRITICAL**: All directory paths in info.txt MUST end with `/`. Missing slash causes silent file-not-found.

### GeoClass.txt (SLC definitions)
```
!! SLC_ID  landuse  soil  crop  crop2  rotation  vegtype  special  tiledepth  streamdepth  numlayers  soildepth1  [soildepth2]  [soildepth3]
1   1   1   0   0   0   1   0   0   0   3   0.3   0.6   1.5
2   2   2   1   0   0   2   0   0.8   0   3   0.3   0.9   1.8
3   3   3   0   0   0   0   2   0   0   1   5.0
```
- `numlayers` determines how many soildepth columns follow (1-3)
- `special=2` marks water class (lake/river)
- `vegtype`: 1=conifer, 2=deciduous, 3=grass, 0=bare/water

### GeoData.txt (Subbasin properties)
```
SUBID  MAINDOWN  AREA  SLC_1  SLC_2  SLC_3  RIVLEN  LATITUDE  LONGITUDE  ELEV_MEAN  SLOPE_MEAN  LAKE_DEPTH
1      3         1.5E8 0.60   0.30   0.10   15000   31.50     117.00     120        0.05        2.0
2      3         2.0E8 0.40   0.50   0.10   20000   31.30     117.20     85         0.03        1.5
3      0         5.0E8 0.35   0.45   0.20   25000   31.10     117.10     45         0.02        3.0
```
- `MAINDOWN=0` marks the outlet subbasin
- `AREA` is in m^2
- `RIVLEN` is main river length in meters within the subbasin
- SLC fractions MUST sum to 1.0 per subbasin

### par.txt (Parameters)
```
!! Land use dependent (nlanduse values per line)
ttmp   0.0   0.0   0.0
cmlt   3.5   4.0   0.0
cevp   0.15  0.20  0.0
srrcs  0.1   0.05  0.0
!! Soil type dependent (nsoil values per line)
wcfc   0.15  0.25  0.05
wcwp   0.05  0.10  0.01
wcep   0.35  0.40  0.50
rrcs1  0.1   0.05  0.0
rrcs2  0.01  0.005 0.0
!! General (1 value per line)
rrcs3  0.001
lp     0.8
rivvel 1.0
damp   0.5
```

**CRITICAL**: Number of values per parameter MUST match:
- Land-use params: exactly `max(landuse IDs in GeoClass)` values
- Soil params: exactly `max(soil IDs in GeoClass)` values
- General params: exactly 1 value
Too few values causes fatal error. Too many causes warning but is ignored.

### Pobs.txt / Tobs.txt (Forcing data)
```
DATE       1      2      3
2005-01-01 2.5    3.1    1.8
2005-01-02 0.0    0.5    0.0
...
```
- Daily values, tab-separated
- Column headers are SUBID numbers matching GeoData.txt
- Pobs.txt: precipitation in mm/day
- Tobs.txt: temperature in degrees Celsius
- Missing values: -9999

### ForcKey.txt (Forcing-subbasin mapping)
```
SUBID   FROSESSION
1       1
2       2
3       3
```
Maps each subbasin to a forcing observation station. Usually 1:1 for gridded forcing.

### Qobs.txt (Observed discharge, optional)
```
DATE       3
2005-01-01 15.2
2005-01-02 14.8
...
```
- Only subbasins with gauges need columns
- Units: m^3/s

---

## Unit Conversion Table (CRITICAL)

| Variable | HYPE expects | CMFD native | MSWX native | Conversion |
|----------|-------------|-------------|-------------|------------|
| Precipitation | mm/day | mm/3hr | mm/3hr | SUM 8 timesteps per day |
| Temperature | deg C | K (3-hourly) | deg C (3-hourly) | MEAN + subtract 273.15 for CMFD |
| PET forcing | Not needed for petmodel 1-2 | - | - | Jensen-Haise/Hargreaves compute from T |
| SW radiation | MJ/m^2/day | W/m^2 (3-hourly) | W/m^2 (3-hourly) | MEAN x 0.0864 |
| Wind speed | m/s | m/s | m/s | MEAN (only for petmodel 5) |
| Humidity | fraction | kg/kg | kg/kg | Convert to RH (only for petmodel 5) |
| Pressure | hPa | Pa | Pa | /100.0 (only for petmodel 5) |

**CRITICAL**: HYPE uses **daily** forcing. CMFD/MSWX are 3-hourly. You MUST aggregate to daily:
- Precipitation: SUM over 8 timesteps (not average!)
- Temperature: MEAN over 8 timesteps
- Radiation: MEAN over 8 timesteps, then convert to MJ/m^2/day

For `petmodel 1` (Jensen-Haise, default) or `petmodel 2` (Hargreaves), only P and T are needed.
For `petmodel 5` (Penman-Monteith), additional forcing files are required: SWobs.txt, Uobs.txt, RHobs.txt, SFobs.txt.

---

## Pipeline Stages

```
s1_subbasin_delineation   Delineate subbasins + MAINDOWN topology from DEM
        |
s2_slc_classification     Compute SLC fractions from landcover + soil data
        |
s3_forcing_preparation    Convert CMFD/MSWX 3-hourly to daily Pobs.txt + Tobs.txt
        |
s4_geodata_generation     Generate GeoData.txt + GeoClass.txt
        |
s5_parameter_setup        Set up par.txt from WWH defaults or literature
        |
s6_lake_reservoir_config  Configure LakeData.txt and DamData.txt (optional)
        |
s7_execution              Run HYPE, parse log, verify completion
        |
s8_output_analysis        Parse timeCOUT.txt/mapCOUT.txt, compute metrics, compare with VIC
        |
s9_water_quality          Enable N/P simulation, configure NPC parameters, parse nutrient output
        |
s10_calibration           Built-in calibration (DDS/DEMC/MC) with optpar.txt + criteria
```

---

## Key Parameters

### General Parameters
| Parameter | Description | Default | Range | Sensitivity |
|-----------|------------|---------|-------|------------|
| lp | Limit for PET reduction | 0.8 | 0.1-1.0 | High |
| rivvel | River velocity (m/s) | 1.0 | 0.1-5.0 | Moderate |
| damp | Damping coefficient | 0.5 | 0.0-1.0 | Moderate |
| cevpam | Amplitude of PET seasonal cycle | 0.3 | 0.0-1.0 | High |
| cevpph | Phase shift of PET (days) | 30 | 0-365 | Low |
| rrcs3 | Deep groundwater recession | 0.001 | 0.0-0.1 | Moderate |

### Land-Use Dependent Parameters
| Parameter | Description | Range | Calibrate? |
|-----------|------------|-------|-----------|
| ttmp | Threshold temperature for snow (C) | -3 to 3 | Yes |
| cmlt | Degree-day snowmelt factor (mm/C/day) | 1-10 | Yes |
| cevp | PET coefficient | 0.05-0.5 | Yes |
| srrcs | Surface runoff recession coefficient | 0.0-1.0 | Yes |

### Soil-Type Dependent Parameters
| Parameter | Description | Range | Calibrate? |
|-----------|------------|-------|-----------|
| wcfc | Field capacity (fraction) | 0.05-0.5 | Yes |
| wcwp | Wilting point (fraction) | 0.01-0.3 | Yes |
| wcep | Effective porosity (fraction) | 0.1-0.7 | Yes |
| rrcs1 | Upper soil recession coefficient | 0.0-1.0 | Yes |
| rrcs2 | Lower soil recession coefficient | 0.0-0.5 | Yes |

---

## Lake and Reservoir Configuration (Stage s6)

HYPE has native support for outlet lakes (olake) and regulated dams. Lakes modify
the flow hydrograph by adding storage and attenuation; dams add active regulation
rules (production flow, flood control, seasonal operation).

### When to Enable Lakes/Reservoirs

- Basin contains significant lakes (>1 km^2) or reservoirs
- Flow hydrograph shows reservoir regulation effects (sustained low flows, abrupt releases)
- GRanD shows dams within or upstream of the basin

### Prerequisites

1. **GeoClass.txt** must have an SLC with `special=2` (outlet lake class)
2. **GeoData.txt** must have:
   - `SLC_N` fraction > 0 for the olake SLC in subbasins with lakes
   - `lake_depth` column with depth in meters
   - `lakedataid` column linking subbasins to LakeData rows
3. LakeData.txt goes in `modeldir/` (same as GeoData.txt)
4. DamData.txt goes in `modeldir/` (same as GeoData.txt)

**CRITICAL**: Do NOT set `special=2` on any SLC class unless LakeData.txt is
provided. Without it, HYPE creates a zero-volume lake that traps all water.

### Generating LakeData.txt

```bash
# Search HydroLAKES + GRanD for lakes/dams within the basin area:
python tools/s6_lake_reservoir_config/generate_lakedata.py \
    --geodata modelfiles/GeoData.txt \
    --geoclass modelfiles/GeoClass.txt \
    --output modelfiles/LakeData.txt \
    --lat [LAT] --lon [LON] \
    --search_radius_km 100 \
    --min_lake_area_km2 1.0 \
    --update_geodata
```

The `--update_geodata` flag automatically adds `lakedataid` and updates
`lake_depth` in GeoData.txt from HydroLAKES data.

### Generating DamData.txt

```bash
# Search GRanD for regulated dams near the basin:
python tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata modelfiles/GeoData.txt \
    --output modelfiles/DamData.txt \
    --lat [LAT] --lon [LON] \
    --search_radius_km 200

# Or by specific dam names:
python tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata modelfiles/GeoData.txt \
    --output modelfiles/DamData.txt \
    --dam_names "Meishan,Xianghongdian,Foziling"

# Filter by purpose (3=flood control):
python tools/s6_lake_reservoir_config/generate_damdata.py \
    --geodata modelfiles/GeoData.txt \
    --output modelfiles/DamData.txt \
    --lat 32.4 --lon 115.7 --purpose 3
```

### LakeData.txt Column Reference

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| lakedataid | int | - | Links to GeoData lakedataid column (REQUIRED) |
| ldtype | int | - | 1=simple olake, 5=outlet1, 6=outlet2, 7=equal-level basin (REQUIRED) |
| area | real | m^2 | Lake surface area |
| lake_depth | real | m | Mean lake depth (overrides GeoData value) |
| lake_shape | real | - | Depth exponent (1.0=flat, 2.0=conical) |
| rate | real | - | Rating curve coefficient |
| exp | real | - | Rating curve exponent (typically 1.5) |
| w0ref | real | m | Reference water level threshold |
| regvol | real | Mm^3 | Regulation volume (for regulated lakes) |
| wamp | real | m | Regulation amplitude |
| qprod1 | real | m^3/s | Production flow, period 1 |
| qprod2 | real | m^3/s | Production flow, period 2 |
| datum1 | int | MMDD | Start date for production period 1 |
| datum2 | int | MMDD | Start date for production period 2 |
| minflow | real | m^3/s | Minimum environmental flow |

### DamData.txt Column Reference

| Column | Type | Unit | Description |
|--------|------|------|-------------|
| subid | int | - | Subbasin ID matching GeoData (REQUIRED) |
| purpose | int | - | 1=Irrigation, 2=WaterSupply, 3=FloodControl, 4=Hydropower |
| lake_depth | real | m | Reservoir mean depth |
| regvol | real | Mm^3 | Regulation volume (dam capacity) |
| rate | real | - | Spillway rating curve coefficient |
| exp | real | - | Spillway rating curve exponent |
| w0ref | real | m | Reference spill level |
| wamp | real | m | Regulation amplitude |
| qprod1/qprod2 | real | m^3/s | Seasonal production flows |
| datum1/datum2 | int | MMDD | Season boundary dates |
| qinfjan-qinfdec | real | m^3/s | Monthly natural inflows (12 columns) |
| minflow | real | m^3/s | Minimum environmental flow |

### Data Sources

| Input | Data KI | Tool | Coverage |
|-------|---------|------|----------|
| Lake area, depth, volume | HydroLAKES v10 | `search_lakes.py` | Global, lakes >= 10 ha |
| Dam capacity, height, year | GRanD | `search_dams.py` | Global, 7,320 large dams |

### Key Lake Parameters (par.txt)

| Parameter | Type | Description | Default | Range |
|-----------|------|-------------|---------|-------|
| gratk | genpar | General lake rating curve coefficient | 1.0 | 0.01-10 |
| gratefk | genpar | General rating curve exponent factor | 1.5 | 1.0-3.0 |
| gldepi | genpar | Internal lake depth (m) | 1.0 | 0.5-10 |
| gldepol | genpar | General olake depth (m) | 5.0 | 1-50 |

### HYPE Lake Outflow Logic (from sw_proc.f90)

For **unregulated lakes** (regvol not set):
```
if water_level > w0ref:
    outflow = rate * (water_level - w0ref)^exp
else:
    outflow = 0
```

For **regulated lakes** (regvol > 0, wmin calculated):
```
if water_level > w0ref:
    outflow = max(rating_curve_flow, production_flow)
elif water_level > wmin:
    outflow = production_flow
else:
    outflow = 0
```
where `wmin = -regvol * 1e6 / lake_area_m2` (negative = below threshold).

### Known Issues

1. **Lumped setup limitation**: With 1 subbasin, the lake IS the entire basin outlet.
   All water passes through the lake, which may over-attenuate the hydrograph.
   Use multi-subbasin setups for realistic lake routing.

2. **Rating curve calibration**: Generated rating curves are estimates.
   Calibrate `rate` and `exp` against observed discharge downstream of the lake.

3. **Monthly inflows in DamData**: The `qinfjan-qinfdec` values are estimated
   from area-runoff relationships. For accurate dam regulation, run a natural
   (no-dam) simulation first and use those monthly flows.

4. **LakeData vs DamData**: Both files can exist simultaneously. DamData
   provides additional regulation on top of LakeData configuration.

---

## Running HYPE

```bash
# From the directory containing info.txt:
KISSPATH_BINARIES/hype/hype ./

# Or specify a different info directory:
KISSPATH_BINARIES/hype/hype /path/to/run/directory/

# CRITICAL: The argument MUST end with a slash (/)
# Without slash: looks for info.txt at wrong path
```

**Exit codes**:
- 0: Success
- 1: Fatal error (check hyss_*.log in logdir or infodir)
- Other: Fortran runtime error

**Output files**:
- `timeCOUT.txt` -- Simulated discharge at each subbasin (m^3/s)
- `timeROUT.txt` -- Observed discharge (-9999 = missing) (m^3/s)
- `timeSNOW.txt` -- Snow water equivalent (mm)
- `timeEVAP.txt` -- Evapotranspiration (mm/day)
- `timeCPRC.txt` -- Corrected precipitation (mm/day)
- `mapCOUT.txt` -- Spatial map output (periodic averages)

---

## Water Quality: Nitrogen & Phosphorus (NPC) Simulation

HYPE's unique selling point — integrated N/P transport with hydrology. No external
coupling needed. Simulates 4 substance pools: IN (inorganic N), ON (organic N),
SP (soluble P), PP (particulate P).

### Enabling NPC Simulation

```bash
# Step 1: Generate CropData.txt from NPKGRIDS (auto-detects region + reads real fertilizer rates)
python tools/s9_water_quality/generate_cropdata.py \
    --lat 32.4 --lon 115.6 \
    --crops wheat,maize \
    --output modelfiles/CropData.txt

# Step 2: Add REGION column to GeoData.txt (required for NPC)
# Ensure GeoData.txt header includes REGION and each subbasin has REGION=1

# Step 3: Enable N/P in info.txt and add NPC parameters to par.txt
python tools/s9_water_quality/configure_npc.py \
    --info_txt info.txt \
    --par_txt modelfiles/par.txt \
    --substances "N P" \
    --region huai_river \
    --geoclass modelfiles/GeoClass.txt

# Step 4: Run HYPE (same binary, NPC is activated by 'substance N P' in info.txt)
python tools/s7_execution/run_hype.py --project_dir <path>

# Step 5: Parse nutrient output
python tools/s9_water_quality/parse_npc_output.py \
    --result_dir resultdir/ \
    --subbasin_id 1 \
    --basin_area_km2 11573 \
    --output_csv nutrient_loads.csv
```

### Data Sources for NPC

| Input File | Data KI | Tool | Auto? |
|-----------|---------|------|-------|
| CropData.txt | NPKGRIDS + crop calendar | `generate_cropdata.py` | YES |
| GeoData REGION | Manual | Add column | Simple |
| Soil N/P pools (par.txt) | Literature defaults | `configure_npc.py` | YES |
| Freundlich P params | Literature | `configure_npc.py` | YES |

### info.txt NPC Configuration

Add to info.txt to enable nutrient simulation:
```
substance   N P                    !! Enable nitrogen + phosphorus
timeoutput variable cout rout reTN reTP ccIN ccON ccSP ccPP
```

### Key NPC Parameters (par.txt)

| Parameter | Type | Description | Range | Sensitivity |
|-----------|------|-------------|-------|-------------|
| fastn0 | genpar | Initial fast N pool (kg/km²) | 1-100 | Medium |
| fastp0 | genpar | Initial fast P pool (kg/km²) | 0.1-50 | Medium |
| humusn0 | landpar | Humus N pool (kg/km²/m) | 50-500 | High |
| humusp0 | landpar | Humus P pool (kg/km²/m) | 5-50 | High |
| denitrlu | landpar | Land denitrification (kg/m²/day) | 0.0001-0.001 | High |
| denitwr | genpar | River denitrification (kg/m²/day) | 0.001-0.01 | Medium |
| denitwl | genpar | Lake denitrification (kg/m²/day) | 0.0005-0.005 | Medium |
| minerfn | landpar | Fast N mineralization (1/day) | 0.001-0.005 | Medium |
| sedon | genpar | ON sedimentation (kg/m²/day) | 0.0001-0.01 | Medium |
| sedpp | genpar | PP sedimentation (kg/m²/day) | 0.0001-0.01 | Medium |
| soilcoh | soilpar | Soil cohesion for erosion (kPa) | 5-15 | P only |
| soilerod | soilpar | Soil erodibility factor | 0.5-2.0 | P only |

### NPC Output Variables

Use `c1*` (computed main flow) variables for modelled concentrations. The `re*`
variables require observed nutrient data (xobs) and will show -9999 without it.

| Variable | File | Unit | Description |
|----------|------|------|-------------|
| c1TN | timeC1TN.txt | ug/L | Modelled TN in main outflow |
| c1TP | timeC1TP.txt | ug/L | Modelled TP in main outflow |
| c1IN | timeC1IN.txt | ug/L | Inorganic N concentration |
| c1ON | timeC1ON.txt | ug/L | Organic N concentration |
| c1SP | timeC1SP.txt | ug/L | Soluble P concentration |
| c1PP | timeC1PP.txt | ug/L | Particulate P concentration |

**IMPORTANT**: Do NOT use `reTN`, `reIN`, `reSP` — these require observed nutrient
data and output -9999 without it. Always use `c1TN`, `c1IN`, `c1SP` for modelled output.

### Expected Nutrient Yields

| Land use | TN (kgN/ha/yr) | TP (kgP/ha/yr) | Source |
|----------|----------------|----------------|--------|
| Agricultural (China) | 5-20 | 0.5-3 | Chinese watershed studies |
| Agricultural (US Midwest) | 10-40 | 1-5 | SPARROW/USGS |
| Forest | 1-5 | 0.05-0.5 | Background levels |
| Urban | 5-15 | 1-3 | USEPA |

### NPC Warmup Requirements

N/P pools need 3-5 years of warmup to stabilize. Set `nyskip >= 3` in time.sim
or a sufficiently early `bdate` in info.txt. Check that `c1TN` reaches a stable
seasonal pattern before the evaluation period.

### NPC Known Issues

1. **Lumped (1-subbasin) setups produce unrealistic IN/SP concentrations.** Dissolved
   inorganic forms (IN, SP) accumulate without downstream export. Use multi-subbasin
   setups (3+ subbasins) for NPC simulation. Organic/particulate forms (ON, PP) are
   unaffected and work correctly in lumped setups.

2. **GeoClass `special=2` requires LakeData.txt.** Do NOT set special=2 (internal lake)
   on any SLC class unless LakeData.txt is provided. Without it, HYPE creates a zero-
   volume lake that traps all water. Use special=0 for regular water classes.

3. **ForcKey.txt location**: Must be in `forcingdir/`, not `modeldir/`. HYPE looks for
   it in the forcing directory path specified in info.txt.

4. **Pobs/Tobs must NOT have `!!` comment lines.** HYPE expects the header row (DATE
   followed by subbasin IDs) as line 1. Comment lines cause silent data misparse.

---

## VIC-HYPE Coupling Points

HYPE and VIC serve complementary roles in HydroCraft:

| Aspect | VIC | HYPE | Coupling |
|--------|-----|------|---------|
| Forcing | 3-hourly gridded | Daily per-subbasin | CMFD/MSWX -> aggregate to daily for HYPE |
| Soil | Grid-cell parameters | Per soil-type parameters | HWSD shared source |
| Routing | External (Lohmann/CaMa) | Internal (MAINDOWN) | Compare discharge at outlet |
| Water quality | Not supported | N/P transport | HYPE adds nutrient dimension to VIC basins |
| Scale | Any | Subbasin (>10 km^2 typical) | VIC grid -> HYPE subbasins via area-weighted mapping |

**Cross-model comparison**: Use `compare_vic_hype.py` to compare discharge time series at the outlet, computing NSE, KGE, and PBIAS for both models against observations.

---

## Common Errors and Diagnostics

See `diagnostics/triplets.yaml` for the full triplet catalog (24 triplets). Key failure modes:

1. **SLC fractions don't sum to 1.0** -- SILENT ERROR, no warning, wrong water balance
2. **Missing trailing slash in info.txt paths** -- Fatal, but cryptic "file not found" message
3. **par.txt value count mismatch** -- Fatal, must match exact number of land-use/soil types
4. **MAINDOWN topology has cycles** -- Fatal at startup, check ordering
5. **Forcing dates don't match bdate/edate** -- Fatal, forcing must cover entire period
6. **Tab vs space in input files** -- HYPE expects TAB separators, spaces may cause silent misparse

---

## Validated Results

### Bengbu (蚌埠) — Huai River, 1981-1990 (production_validated)

| Metric | Value |
|--------|-------|
| Basin | Huai River @ Bengbu, ~121,330 km² |
| Period | 1980-1990 (1980 warmup, 1981-1990 evaluated) |
| Forcing | CMFD 0.1° 3-hourly → daily |
| Setup | Lumped (1 subbasin), 3 SLC classes |
| NSE | **0.678** |
| KGE | **0.740** |
| R² | 0.712 |
| PBIAS | +19.8% (slight overprediction) |
| Mean obs Q | ~900 m³/s |
| Mean sim Q | ~1,080 m³/s |
| Seasonal cycle | Captured correctly (monsoon peak Jun-Aug) |
| Output | `outputs/bengbu_hype_1980_1990/` |
| Plots | `hype_discharge_comparison.png`, `hype_scatter.png`, `hype_annual_cycle.png` |

**Errors found during validation** (9 run attempts):
1. CMFD precip in kg/m²/s — must ×10800 (dt_u03)
2. GeoClass streamdepth=0 → zero discharge (dt_s08)
3. SLC fractions validation needed (dt_s01)

### Chaohe (潮河) — North China, 2001-2010

| Metric | Value |
|--------|-------|
| Basin | Chaohe @ Zhangjiaofen, ~8,783 km² |
| Period | 2000-2010 (2000 warmup, 2001-2010 evaluated) |
| Setup | Lumped (1 subbasin) |
| Mean sim Q | 21.7 m³/s |
| Literature Q | 31-47 m³/s |
| Assessment | 46% low — needs calibration or semi-distributed setup |

---

## Calibration: Built-in Optimization (Stage s10)

HYPE has a powerful built-in optimization engine in `optim.f90` (3,422 lines) supporting
Monte Carlo, DEMC, staged MC, Brent line search, and quasi-Newton methods. The HYPE binary
handles calibration internally -- no external optimizer is needed.

### Calibration Methods

| Method | Code | Best For | Speed |
|--------|------|----------|-------|
| Monte Carlo | MC | First exploration, identify parameter sensitivity | Fast |
| DEMC (Differential Evolution Markov Chain) | DEMC | Posterior sampling, uncertainty | Medium |
| Staged Monte Carlo | SM | Progressive zoom on parameter space | Medium |
| Brent line search | BN | Local refinement around a good solution | Fast |
| Quasi-Newton BFGS | Q2 | Gradient-based local optimization | Fast |

### Calibration Criteria

| Code | Name | Direction | Recommended For |
|------|------|-----------|-----------------|
| MKG | Mean Kling-Gupta Efficiency | max -> 1 | RECOMMENDED (balanced bias/variability/correlation) |
| MNS | Mean Nash-Sutcliffe Efficiency | max -> 1 | Classic, penalizes bias less |
| TAU | Kendall tau | max -> 1 | Robust to outliers |
| MRE | Mean Relative Error | min -> 0 | Volume bias calibration |
| MAR | Mean Absolute Relative Error | min -> 0 | Absolute volume bias |
| MCC | Mean Correlation Coefficient | max -> 1 | Timing only |
| MDA | Median NSE | max -> 1 | Multi-station calibration |

### Setting Up Calibration

```bash
# Step 1: Set up optpar.txt and add criteria to info.txt
python tools/s10_calibration/setup_calibration.py \
    --method MC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --num_runs 500 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout \
    --outlet_subid 3

# Step 2: Run HYPE (calibration is automatic when calibration=Y in info.txt)
KISSPATH_BINARIES/hype/hype ./

# Step 3: Parse calibration results
python tools/s10_calibration/parse_calibration_results.py \
    --result_dir resultdir/ \
    --output_par best_par.txt \
    --geoclass modelfiles/GeoClass.txt \
    --output_csv calibration_results.csv \
    --plot_convergence convergence.png
```

### DEMC Calibration (Bayesian Posterior Sampling)

```bash
# DEMC requires >= 3 populations. More populations = better exploration but slower.
python tools/s10_calibration/setup_calibration.py \
    --method DEMC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --demc_ngen 100 --demc_npop 5 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout

KISSPATH_BINARIES/hype/hype ./
```

### Calibrating with NPC Parameters

```bash
# Include N/P parameters in calibration
python tools/s10_calibration/setup_calibration.py \
    --method MC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --num_runs 1000 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout \
    --substances "N P"
```

### Calibrating a Subset of Parameters

```bash
# Calibrate only the most sensitive parameters (faster convergence)
python tools/s10_calibration/setup_calibration.py \
    --method MC \
    --geoclass modelfiles/GeoClass.txt \
    --info_txt info.txt \
    --output modelfiles/optpar.txt \
    --num_runs 500 \
    --criterion MKG \
    --crit_variable cout \
    --obs_variable rout \
    --params_subset "lp,cevpam,wcfc,wcwp,wcep,rrcs1,cmlt"
```

### Calibration Output Files

| File | Location | Description |
|------|----------|-------------|
| allsim.txt | resultdir/ | All simulations: criterion + performance + parameters (CSV) |
| bestsims.txt | resultdir/ | Best N parameter sets (same format as allsim.txt) |
| calibration.log | resultdir/ | Detailed calibration progress |

### optpar.txt Format Reference

The file has two sections:
1. **Header** (1 line skipped + 20 info lines): optimization task and method settings
2. **Parameter block**: triplets of (min, max, precision) for each parameter

```
!! Heading (skipped)
task MC                    !! Method code: MC, DE, SM, BN, Q2
task WA                    !! Write all results to allsim.txt
num_mc 500                 !! Number of Monte Carlo runs
num_ens 10                 !! Number of best to keep
cal_log Y                  !! Write calibration.log
!! (reserved)              !! Pad to 20 info lines
...
!! Parameter ranges (min / max / precision triplets)
lp      0.1                !! min value (1 value for general params)
lp      1.0                !! max value
lp      3                  !! decimal precision
wcfc    0.05  0.05         !! min values (nsoil values for soil params)
wcfc    0.50  0.50         !! max values
wcfc    3     3            !! precision
```

When min == max for a parameter, it is NOT calibrated (fixed value).

### info.txt Calibration Settings

Added automatically by setup_calibration.py:
```
calibration Y
crit 1 criterion MKG       !! Criterion code
crit 1 cvariable cout       !! Computed (simulated) variable
crit 1 rvariable rout       !! Recorded (observed) variable
crit 1 weight 1.0           !! Weight for multi-criteria
crit meanperiod 1           !! 1=daily, 2=weekly, 3=monthly
crit subbasin 3             !! Subbasin for single-station calibration
```

### Calibration Tips

1. **Start with MC**: Run 200-500 MC simulations first to identify sensitive parameters
2. **Use KGE (MKG)**: More balanced than NSE -- penalizes bias equally with variability
3. **Warmup matters**: Ensure 1-2 years warmup (bdate before cdate) for stable states
4. **Qobs.txt required**: Calibration needs observed discharge in Qobs.txt (same format as Pobs.txt)
5. **Subset calibration**: For many parameters, calibrate only the most sensitive ones first
6. **Check convergence**: Use parse_calibration_results.py to verify the optimizer has converged
7. **DEMC for uncertainty**: DEMC produces posterior parameter distributions, not just a best fit

---

## Recommendations for Future Runs

1. **Semi-distributed**: For basins >10,000 km², use 5-10 subbasins for routing attenuation
2. **Calibration**: Use `setup_calibration.py` with MC (exploration) or DEMC (posterior), key params: lp, cevpam, cmlt, wcfc, wcwp, wcep, rrcs1. See Stage s10 above.
3. **Nutrient calibration**: Include `--substances "N P"` in setup_calibration.py to calibrate NPC parameters jointly with hydrology
4. **Lake regulation**: Tools available — use `generate_lakedata.py` + `generate_damdata.py` to configure LakeData.txt/DamData.txt from HydroLAKES/GRanD
