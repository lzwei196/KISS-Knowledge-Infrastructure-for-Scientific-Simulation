# Stage 1: Meteorological Forcing Preparation

## Purpose

Convert global reanalysis or station meteorological data into the FSM2 input format:
a space-delimited ASCII file with 12 columns per timestep (DRIV1D=1 format).

## Inputs

| Source | Variables needed | Typical resolution |
|--------|------------------|--------------------|
| ERA5 | t2m, sp, d2m, ssrd, strd, tp, u10, v10 | hourly, 0.25° |
| MSWX | Ta, P, SW, LW, RH, Ua | 3-hourly, 0.1° |
| Station | Same variables from AWS | varies |

## Outputs

- FSM2 meteorological driving file (ASCII, space-delimited)
- One row per timestep, columns: `year month day hour SW LW Sf Rf Ta RH Ua Ps`

## Procedure

1. **Extract point data** from gridded product (nearest neighbour or bilinear).
2. **Derive missing variables**:
   - If only total precipitation: partition into rain/snow using a temperature threshold (e.g., Ta < 275.15 K → all snow).
   - If dewpoint (ERA5): compute RH = 100 * exp(17.625*Td/(243.04+Td)) / exp(17.625*Tc/(243.04+Tc)) where Tc = Ta - 273.15, Td = dewpoint - 273.15.
   - If only u10/v10 components: Ua = sqrt(u10² + v10²).
   - If cumulative radiation (ERA5 ssrd/strd): difference successive accumulations and divide by dt.
3. **Unit conversions** (critical!):
   - Temperature: °C → K (add 273.15)
   - Pressure: hPa → Pa (×100)
   - Precipitation: mm/h → kg/m²/s (÷3600)
   - Relative humidity: fraction → percent (×100)
4. **Write** in FSM2 format: `format(3(i4),f8.3,*(e14.6))` for native, but space-delimited free-format is read.

## Verification

- Check all values are in physical range:
  - Ta: 200-330 K
  - Ps: 40000-110000 Pa
  - RH: 0-100 %
  - SW ≥ 0, LW > 50 W/m²
  - Sf, Rf ≥ 0 and < 0.01 kg/m²/s for hourly data
  - Ua ≥ 0.1 m/s
- Plot time series of all variables — look for spikes, gaps, impossible values.
- Verify precipitation phase: at Ta=273.15K, transition from snow to rain.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Temperature in °C instead of K | Model crashes or no snow accumulates | Add 273.15 |
| Pressure in hPa instead of Pa | Specific humidity near zero → dry bias | Multiply by 100 |
| RH as fraction 0-1 instead of % | Extremely low humidity, unrealistic LE | Multiply by 100 |
| Precipitation in mm/h not kg/m²/s | SWE grows 3600× too fast | Divide by 3600 |
| ERA5 cumulative radiation not deaccumulated | SW/LW monotonically increasing | Difference successive steps |
| Missing snowfall column | No snow accumulation | Partition total precip by temperature |
| Column order wrong | All variables misassigned | Check header against FSM2 DRIV1D format |

## Example

```python
from ki.tools.convert_forcing_to_fsm2 import convert_forcing

result = convert_forcing(
    input_file="era5_hourly.csv",
    output_file="met_site.txt",
    units={"Ta": "C", "Ps": "hPa", "RH": "percent", "Sf": "mm/h", "Rf": "mm/h"},
)
print(f"Wrote {result['n_rows']} timesteps, issues: {result['issues']}")
```
