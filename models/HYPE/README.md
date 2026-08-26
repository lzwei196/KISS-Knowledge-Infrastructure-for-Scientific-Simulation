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

## Recommendations for Future Runs

1. **Semi-distributed**: For basins >10,000 km², use 5-10 subbasins for routing attenuation
2. **Calibration**: DDS optimizer with NSE objective, key params: lp, cevpam, cmlt, wcfc, wcwp, wcep, rrcs1
3. **Nutrient simulation**: Not yet tested — add substance N P to info.txt with nutrient params in par.txt
4. **Lake regulation**: Not yet tested — configure LakeData.txt from HydroLAKES for basins with significant lakes
