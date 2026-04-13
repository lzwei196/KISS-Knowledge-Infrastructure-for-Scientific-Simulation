# Stage 1: Forcing Preparation

## Purpose

Convert global meteorological forcing data (CMFD, ERA5, or gauge observations) into the format required by airGR's GR4J model. GR4J requires only two forcing variables: **precipitation** and **potential evapotranspiration**, both in mm/day. This stage handles unit conversions, temporal aggregation, and PE computation.

## Inputs

| Input | Source | Format | Unit |
|-------|--------|--------|------|
| Precipitation | CMFD, ERA5, gauge | NetCDF or CSV | mm/3hr (CMFD), mm/hr (ERA5), mm/day (gauge) |
| Temperature | CMFD, ERA5, gauge | NetCDF or CSV | K (CMFD/ERA5), degC (gauge) |
| Latitude | DEM or manual | Scalar | degrees |
| Observed discharge (optional) | Gauge station | CSV | m3/s, l/s, or mm/day |
| Catchment area (optional) | Shapefile or manual | Scalar | km2 |

## Outputs

| Output | Format | Columns | Unit |
|--------|--------|---------|------|
| airGR forcing CSV | CSV | Date, Precip_mm, PotEvap_mm, TempMean_degC, [Qobs_mm] | mm/day |

## Procedure

### Step 1: Read raw forcing data
- Support CMFD 3-hourly NetCDF or pre-extracted CSV
- Extract catchment-average values (spatial mean over catchment grid cells)

### Step 2: Temperature conversion
- CMFD/ERA5: subtract 273.15 to convert K to degC
- **TRAP (UT-001)**: If mean temperature > 200, data is in Kelvin — convert
- **TRAP (UT-001)**: Forgetting this conversion causes PE = 300 mm/day

### Step 3: Precipitation aggregation
- Sum sub-daily values to daily totals
- CMFD 3-hourly: sum 8 timesteps per day
- **TRAP (UT-003)**: Averaging instead of summing gives 1/8 of correct value
- **TRAP (UT-002)**: If precip is in m/day instead of mm/day, values ~1000x too small

### Step 4: Compute potential evapotranspiration
- Use PE_Oudin formula: `PE = GE * (T + 5) / 100 / 28.5` when T >= -5 degC
- GE depends on latitude and Julian day (extraterrestrial radiation)
- **TRAP (UT-007)**: If using pre-computed PE in mm/month, divide by ~30

### Step 5: Convert observed discharge (if available)
- m3/s to mm/day: `Qmm = Q_m3s * 86.4 / area_km2`
- l/s to mm/day: `Qmm = Q_ls * 0.0864 / area_km2`
- **TRAP (UT-004, UT-005)**: Using m3/s or l/s directly without conversion causes calibration failure (NSE = -infinity)

### Step 6: Quality checks
- No missing values in Precip or PE (airGR requirement)
- No negative values in Precip or PE
- Gap-fill with interpolation or nearest-neighbor if needed

## Verification

1. **Precipitation range**: Daily precip should be 0-200 mm/day for most catchments
2. **PE range**: Daily PE should be 0-15 mm/day for most catchments
3. **Temperature range**: Should be -30 to +45 degC for most catchments
4. **Qobs range**: Should be physically reasonable for catchment size
5. **Record completeness**: No gaps, no NA values in P and PE

## Traps

| ID | Trap | Silent? | Detection |
|----|------|---------|-----------|
| UT-001 | Temperature in K instead of degC | Yes | PE > 50 mm/d |
| UT-002 | Precip in m/day instead of mm/day | Yes | Mean precip < 0.01 |
| UT-003 | Sub-daily precip averaged, not summed | Yes | Total annual P much too low |
| UT-004 | Qobs in m3/s not converted to mm/d | Yes | NSE = -infinity |
| UT-005 | Qobs in l/s not converted | Yes | Calibration diverges |
| UT-007 | PE in mm/month not mm/day | Yes | Store drains instantly |
| UT-008 | Negative PE values | Warning | airGR raises warning |

## Example

```python
from tools.convert_forcing_to_gr4j import convert_cmfd_to_airgr

df = convert_cmfd_to_airgr(
    cmfd_csv="data/cmfd_bengbu.csv",
    lat_deg=32.95,
    output_csv="forcing_gr4j.csv",
    area_km2=121330,
    qobs_csv="data/obs_bengbu.csv",
)
# Expected: ~8000 daily records with columns Date, Precip_mm, PotEvap_mm, TempMean_degC, Qobs_mm
```
