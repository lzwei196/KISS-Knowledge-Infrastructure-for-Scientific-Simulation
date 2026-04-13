# S3: Climatic Constraints (Module III) Skill Document

## Purpose

Apply agro-climatic yield reduction factors (fc3) that account for sub-optimal
climate conditions not captured by the biomass/water balance in Module II. The fc3
factor combines constraints from temperature regime, wetness pattern, and LGP
duration using lookup tables specific to each crop.

## Inputs

| Variable | Type | Shape | Unit | Source |
|----------|------|-------|------|--------|
| `yield_rain` | NumPy | (H,W) | kg/ha | Module II |
| `yield_irr` | NumPy | (H,W) | kg/ha | Module II |
| `lgp` | NumPy | (H,W) | days | Module I |
| `lgp_equv` | NumPy | (H,W) | days | Module I |
| `lgpt10` | NumPy | (H,W) | days | Module I |
| Climate data | NumPy | (H,W,12/365) | various | S0 |
| `elevation` | NumPy | (H,W) | meters | GeoTIFF |
| `mask` | NumPy | (H,W) | 0/1 | GeoTIFF |
| fc3 lookup Excel | .xlsx | — | — | User |

### fc3 Excel Sheet Structure

The Excel file contains reduction factors organized by:
- **Sheet "mean>20"**: For pixels with annual mean temp ≥ 20°C
- **Sheet "mean<10"**: For pixels with annual mean temp < 10°C
- **Rows B, C, D, E**: Different constraint components
- **Columns**: LGP classes and wetness day counts

## Outputs

| Variable | Shape | Unit | Description |
|----------|-------|------|-------------|
| `clim_yield_rain` | (H,W) | kg/ha | Climate-constrained rainfed yield |
| `clim_yield_irr` | (H,W) | kg/ha | Climate-constrained irrigated yield |
| `fc3_rain` | (H,W) | 0–1 | Climate constraint factor (rainfed) |
| `fc3_irr` | (H,W) | 0–1 | Climate constraint factor (irrigated) |

## Procedure

### Step 1: Initialize
```python
from pyaez import ClimaticConstraints
clim_con = ClimaticConstraints.ClimaticConstraints(
    lat_min, lat_max, elevation, mask, no_mask_value=0)
```

### Step 2: Load climate data
```python
clim_con.setClimateData(min_temp=min_temp, max_temp=max_temp,
                        wind_speed=wind, short_rad=srad,
                        rel_humidity=humidity, precip=precip)
```

### Step 3: Load fc3 reduction factors
```python
clim_con.setReductionFactors(file_path='maiz_fc3_rain_lst.xlsx')
```

### Step 4: Apply constraints
```python
clim_con.applyClimaticConstraints(
    yield_input=yield_rain,
    lgp=lgp, lgp_equv=lgp_equv, lgpt10=lgpt10,
    omit_yld_0=True)  # Skip pixels with zero yield
```

### Step 5: Extract results
```python
clim_yield = clim_con.getClimateAdjustedYield()  # kg/ha
fc3 = clim_con.getClimateReductionFactor()        # 0–1
```

## Verification

1. **fc3 range**: 0–1; most productive areas should have fc3 close to 1.0
2. **Yield reduction**: clim_yield ≤ input yield for every pixel
3. **Spatial pattern**: fc3 should be lower in areas with extreme temperatures or short LGP
4. **Excel integrity**: Check that all B/C/D/E rows have values, no empty cells
5. **Temperature interpolation**: For mean T between 10–20°C, linear interpolation between sheets

## Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| fc3 = 0 everywhere | Wrong Excel file or sheet names | Verify sheet names match code expectation |
| fc3 = 1 everywhere | LGP too long (precip in wrong unit) | Check precip → LGP chain |
| fc3 discontinuous | Missing LGP classes in lookup table | Fill all rows in Excel |
| Wrong crop fc3 file | Silent wrong reduction | Each crop needs its own fc3 Excel |

## Example

```python
from pyaez import ClimaticConstraints
clim_con = ClimaticConstraints.ClimaticConstraints(13.87, 22.59, elev, mask, 0)
clim_con.setClimateData(min_temp=min_temp, max_temp=max_temp,
                        wind_speed=wind, short_rad=srad,
                        rel_humidity=rhum, precip=precip)
clim_con.setReductionFactors('maiz_fc3_rain_lst.xlsx')
clim_con.applyClimaticConstraints(yield_rain, lgp, lgp_equv, lgpt10)
fc3 = clim_con.getClimateReductionFactor()
print(f"fc3 range: {fc3[mask>0].min():.2f} – {fc3[mask>0].max():.2f}")
```
