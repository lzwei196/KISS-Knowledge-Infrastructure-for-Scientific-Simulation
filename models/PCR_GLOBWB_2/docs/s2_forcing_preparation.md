# Stage 2: Meteorological Forcing Preparation

## Purpose

Convert global meteorological datasets (ERA5, CMFD, CRU-ERA-Interim, W5E5) to PCR-GLOBWB 2 compatible NetCDF format with correct variable names and units (meters, Celsius).

## Inputs

| Input | Format | Unit (source) | Description |
|-------|--------|---------------|-------------|
| Precipitation | NetCDF | mm/day or kg/m2/s | Daily precipitation |
| Temperature | NetCDF | K or degC | Daily mean air temperature |
| Reference ET | NetCDF | mm/day | Daily reference potential evapotranspiration |

## Outputs

| Output | Format | Unit (PCR-GLOBWB) | Variable Name |
|--------|--------|-------------------|---------------|
| Precipitation | NetCDF | m/day | `precipitation` |
| Temperature | NetCDF | degrees Celsius | `temperature` |
| Reference ET | NetCDF | m/day | `referencePotET` or `evapotranspiration` |

## Procedure

1. **Identify source format**: Determine which dataset you have (ERA5, CMFD, W5E5, etc.)
2. **Apply unit conversions**:
   - **Precipitation**: Most sources provide mm/day → divide by 1000 for m/day (dt_001)
   - **Temperature**: ERA5/W5E5 provide Kelvin → subtract 273.15 for Celsius (dt_002)
   - **Reference ET**: Most sources provide mm/day → divide by 1000 for m/day (dt_003)
   - **W5E5 precipitation**: kg/m2/s → multiply by 86400/1000 for m/day
3. **Ensure correct variable names** (dt_009):
   - Must be exactly: `precipitation`, `temperature`, `referencePotET`
   - Case-sensitive — `Precipitation` or `PRECIP` will NOT work
4. **Clip negative values**: Precipitation and ET must be >= 0
5. **Verify spatial extent**: Must cover the clone map domain
6. **Match temporal coverage**: Must span startTime to endTime in the .ini file

### Reference ET: derive it whenever radiation/wind/humidity exist

Inspect the forcing's variable list **before** choosing a PET method. If the source
carries radiation, wind, humidity and pressure -- CMFD V0200 ships `srad`, `wind`,
`shum`, `pres` -- compute FAO-56 Penman-Monteith refET and feed it to the model:

1. `convert_forcing_to_pcrglobwb.build_from_ki_forcing(..., refet_method='penman')`
   (the default) writes `referencePotET.nc`.
2. Set `referenceETPotMethod = Input` and
   `refETPotFileNC = global_30min/meteo/forcing/referencePotET.nc`.
3. The NetCDF variable must be named `evapotranspiration` -- PCR-GLOBWB's default
   `referenceEPotVariableName` (`model/meteo.py:177`).

### Fallback: Hamon ET Method

Only if the forcing genuinely lacks radiation/wind/humidity, set
`referenceETPotMethod = Hamon` in `[meteoOptions]`; the model then computes reference
ET from temperature alone using the Hamon (1963) method.

**Caveat (dt_031):** temperature-only Hamon under-estimates PET in cold continental
monsoon basins (~665 vs ~907 mm/yr at Songhua). PCR-GLOBWB caps actualET by
referencePotET, so the un-evaporated water leaves as runoff and routes to the outlet,
inflating discharge (+76% PBIAS at Songhua while r stayed 0.864, NSE -0.537). The run
completes silently and the hydrograph *shape* still looks right.

## Verification

- [ ] Precipitation max < 0.5 m/day for most climates (extreme events may reach 0.3 m/day)
- [ ] Temperature range: -60 to +60 deg C globally
- [ ] Reference ET range: 0 to 0.02 m/day for most regions
- [ ] Variable names match exactly: `precipitation`, `temperature`, `referencePotET`
- [ ] No negative precipitation or ET values
- [ ] Temporal coverage matches simulation period

## Traps

| Trap ID | Symptom | Root Cause | Fix |
|---------|---------|-----------|-----|
| dt_001 | Flooding, unrealistic runoff | Precip in mm/day instead of m/day | Divide by 1000 |
| dt_002 | No snow, wrong ET | Temperature in Kelvin instead of Celsius | Subtract 273.15 |
| dt_003 | Excessive ET, soil always dry | RefET in mm/day instead of m/day | Divide by 1000 |
| dt_009 | Model reads zeros, silent failure | Wrong NetCDF variable name | Rename to `precipitation` etc. |

## Example

```python
from tools.convert_forcing_to_pcrglobwb import process, validate_outputs

# Convert ERA5 forcing
process(
    precip_nc="era5_tp_2000_2010.nc",
    temp_nc="era5_t2m_2000_2010.nc",
    refet_nc="era5_pet_2000_2010.nc",
    output_dir="./forcing_pcrglobwb/",
    source_format="era5"
)

# Validate
validate_outputs("./forcing_pcrglobwb/", "2000-01-01", "2010-12-31")
```

### Unit Conversion Quick Reference

| Source | Precip | Temperature | ET |
|--------|--------|-------------|-----|
| ERA5 | mm/day ÷ 1000 | K - 273.15 | mm/day ÷ 1000 |
| CMFD | mm/day ÷ 1000 | K - 273.15 | mm/day ÷ 1000 |
| CRU-ERA-Interim | already m/day | already degC | already m/day |
| W5E5 | kg/m2/s × 86.4 | K - 273.15 | mm/day ÷ 1000 |
