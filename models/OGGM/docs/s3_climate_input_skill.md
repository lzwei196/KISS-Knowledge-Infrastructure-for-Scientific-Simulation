# Stage 3: Climate Data Processing

## Purpose

Process climate data for glacier mass balance computation. OGGM's mass balance model requires monthly temperature (degC) and precipitation (kg/m2/month) at each glacier's location and reference elevation. This stage handles three scenarios: (1) standard climate datasets (W5E5, CRU, ERA5), (2) custom climate from HydroCraft forcing (CMFD/MSWX), and (3) CMIP6 projections for future glacier simulations. Climate data quality directly controls mass balance accuracy — a 1 degC temperature bias shifts the equilibrium line altitude by ~150m and can flip a glacier from growing to shrinking.

## Prerequisites

- **Preprocessed glacier directories** (Stage 2 completed, GDirs exist with DEM and flowlines)
- **Internet connection** for downloading W5E5/CRU/ERA5 data (first use only, cached afterward)
- **For custom climate**: HydroCraft forcing data (CMFD or MSWX) covering glacier locations
- **For CMIP6**: GCM/SSP selection; baseline climate already processed

## Inputs

### Baseline Climate

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | OGGM working directory |
| `source` | string | No | 'W5E5' (default), 'CRU', 'ERA5' |
| `ref_period` | string | No | Reference period 'YYYY-YYYY' (default '2000-2020') |

### Custom Climate (CMFD/MSWX)

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | OGGM working directory |
| `climate_dir` | directory | Yes | HydroCraft forcing directory |
| `format` | string | Yes | 'CMFD' or 'MSWX' |
| `start_year` | int | Yes | Start year |
| `end_year` | int | Yes | End year |

### CMIP6 Projections

| Input | Type | Required | Description |
|-------|------|----------|-------------|
| `working_dir` | directory | Yes | OGGM working directory |
| `gcm` | string | Yes | GCM name (e.g., 'BCC-CSM2-MR') |
| `ssp` | string | Yes | Scenario: 'ssp126', 'ssp245', 'ssp370', 'ssp585' |
| `start_year` | int | Yes | Projection start |
| `end_year` | int | Yes | Projection end |

## Procedure

### Step 1: Select Climate Dataset

**Decision matrix:**

| Condition | Dataset | Resolution | Period | Quality |
|-----------|---------|-----------|--------|---------|
| Global, standard | W5E5 | 0.5 deg | 1979-2019 | Best (ERA5 downscaled) |
| Long-term needed | CRU TS4 | 0.5 deg | 1901-present | Moderate (gauge-based) |
| High-res reanalysis | ERA5 | 0.25 deg | 1979-present | High (needs API key) |
| China, consistent with VIC | CMFD | 0.1 deg | 1979-2018 | High (China-specific) |
| Global, consistent with VIC | MSWX | 0.1 deg | 1979-2026 | High |

**W5E5 is recommended** for standard use. It is the default in OGGM v1.6 and is what the Hugonnet 2021 geodetic mass balance calibration was tuned against. Using a different climate dataset means recalibration may be needed.

### Step 2: Process Baseline Climate

For standard datasets:

```python
from oggm import tasks, workflow

# W5E5 (recommended)
workflow.execute_entity_task(tasks.process_w5e5_data, gdirs)

# CRU
workflow.execute_entity_task(tasks.process_cru_data, gdirs)

# ERA5 (requires Climate Data Store API)
workflow.execute_entity_task(tasks.process_era5_daily_data, gdirs)
```

Each task downloads the global climate dataset (once, ~4-8 GB), extracts monthly values at each glacier's location, applies a temperature lapse rate correction from the climate grid elevation to the glacier's reference height, and saves the result as `climate_historical.nc` in each GDir.

**Key variables in climate_historical.nc:**
- `temp` — Monthly mean temperature at reference height (degC)
- `prcp` — Monthly total precipitation (kg/m2/month)
- `ref_hgt` — Reference height for temperature (m a.s.l.)
- `ref_pix_lat`, `ref_pix_lon` — Climate grid cell coordinates

### Step 3: Process Custom Climate (CMFD/MSWX)

To use HydroCraft forcing data instead of standard datasets:

1. **Extract temperature**: From CMFD/MSWX 3-hourly files, compute monthly mean temperature. CMFD temperature is in Kelvin — subtract 273.15 to get degC.
2. **Extract precipitation**: Sum 3-hourly precipitation to monthly totals. Convert from mm/3hr to kg/m2/month (1 mm = 1 kg/m2).
3. **Compute reference height**: Extract elevation from the forcing DEM at each glacier's grid cell.
4. **Apply lapse rate**: If glacier elevation differs significantly from grid cell elevation, apply temperature correction: T_glacier = T_grid + lapse_rate * (z_glacier - z_grid) / 1000. Default lapse rate = -6.5 degC/km.
5. **Create OGGM-compatible NetCDF**: Format with dimensions (time,) and variables (temp, prcp, ref_hgt).

**Advantage of CMFD/MSWX**: Higher spatial resolution (0.1 deg vs. 0.5 deg) means better temperature and precipitation estimates in complex mountain terrain. This can significantly improve mass balance accuracy for individual glaciers.

**Disadvantage**: Requires recalibration since the default OGGM calibration is tuned for W5E5.

### Step 4: Process CMIP6 Projections

For future glacier simulations under climate change scenarios:

```python
from oggm.shop import gcm_climate

# Download and process GCM data
for ssp in ['ssp126', 'ssp245', 'ssp585']:
    rid = f'{gcm}_{ssp}'
    workflow.execute_entity_task(
        gcm_climate.process_cmip_data, gdirs,
        filesuffix=f'_{rid}',
        fpath_temp=temp_file,
        fpath_precip=prcp_file
    )
```

The delta method for bias correction:
- **Temperature**: T_future(month) = T_baseline(month) + [T_gcm_future(month) - T_gcm_hist(month)]
- **Precipitation**: P_future(month) = P_baseline(month) * [P_gcm_future(month) / P_gcm_hist(month)]

**CRITICAL CHECK (dt_010)**: Verify GCM temperature is in Celsius. Many CMIP6 outputs use Kelvin. If monthly mean temperatures are ~270-290, they are in Kelvin. Subtract 273.15. This is completely silent — the mass balance will be wildly wrong (all glaciers gain mass because "temperature" is always below freezing threshold in the model).

### Step 5: Precipitation Correction Factor

Mountain precipitation is systematically underestimated by gridded datasets due to:
- Gauge undercatch (wind, solid precipitation)
- Orographic enhancement below grid resolution
- Valley-floor gauge bias (glaciers are on ridges, gauges in valleys)

Typical precipitation correction factors (pcf):
- Low-altitude glaciers (Alps, Scandinavia): 1.0-2.0
- High-altitude glaciers (Himalaya, Karakoram): 2.0-4.0
- Extreme cases (windward slopes, monsoon interception): up to 5.0

The pcf is calibrated jointly with mu_star in Stage 4. However, providing a reasonable initial estimate speeds convergence.

## Expected Outputs

| Output | Location | Description |
|--------|----------|-------------|
| `climate_historical.nc` | Per GDir | Monthly temp (degC) and precip (kg/m2/month) |
| `gcm_data_{gcm}_{ssp}.nc` | Per GDir | Bias-corrected CMIP6 projections |

## Validation Checks

1. **Temperature units** — Monthly mean temperature should be in degC (typical glacier range: -30 to +15 degC). Values > 100 indicate Kelvin.
2. **Precipitation non-negative** — All monthly precipitation values >= 0
3. **Time coverage** — Climate data covers the required period (at minimum, the reference period for calibration)
4. **Elevation consistency** — ref_hgt should be within ~500m of the glacier's median elevation
5. **No NaN values** — Missing months cause mass balance computation failure
6. **Seasonal cycle** — Temperature should show a clear annual cycle (cold winters, warm summers for NH glaciers)

## Common Pitfalls

### Climate Period Doesn't Overlap Geodetic MB (dt_009)
Hugonnet 2021 geodetic mass balance covers 2000-2020. If your climate data ends before 2000 or starts after 2020, there is no overlap for calibration. Solution: use W5E5 (1979-2019) or extend with ERA5.

### CMIP6 Temperature in Kelvin (dt_010)
The most dangerous silent error in the climate pipeline. Always verify: if mean annual temperature at a Himalayan glacier is ~280, it is Kelvin. Convert before processing.

### Download Failures (dt_008)
Climate data downloads from CRU, ERA5, or CMIP6 servers can fail due to server maintenance or network issues. OGGM caches downloads — retry after the server is back.

### Lapse Rate Sensitivity
The default -6.5 degC/km lapse rate is the moist adiabatic rate. In dry continental climates (Central Asia, Tibetan Plateau), the actual lapse rate may be -7 to -8 degC/km. A 1 degC/km error in lapse rate over a 1000m elevation difference introduces a 1 degC bias in glacier temperature — enough to significantly affect mass balance.

### CMFD vs. MSWX Quirks
- **CMFD**: Temperature is Kelvin, precipitation is mm/hr. China-only coverage.
- **MSWX**: Temperature is Celsius, precipitation is mm/day. Global coverage. Files are 3-16 GB — extraction is slow.

When using either as custom OGGM climate, ensure unit conversion is exact. Off-by-one-order-of-magnitude precipitation errors are common.

## Tools Reference

| Tool | Script | Purpose |
|------|--------|---------|
| `process_climate_baseline` | `tools/s3_climate_input/process_climate_baseline.py` | Standard climate processing |
| `process_custom_climate` | `tools/s3_climate_input/process_custom_climate.py` | CMFD/MSWX conversion |
| `process_cmip6_projections` | `tools/s3_climate_input/process_cmip6_projections.py` | CMIP6 bias correction |
