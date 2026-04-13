# S2: Crop Simulation (Module II) Skill Document

## Purpose

Simulate crop biomass accumulation and water-limited yield for every possible planting
date (DOY 1–365) at each pixel. Determines the optimal crop calendar and maximum
attainable yield under rainfed and irrigated conditions. Also computes fc1 (thermal
screening factor) and fc2 (moisture reduction factor).

## Inputs

| Variable | Type | Shape | Unit | Source |
|----------|------|-------|------|--------|
| All climate arrays | NumPy | (H,W,12/365) | various | S0 |
| `elevation` | NumPy | (H,W) | meters | GeoTIFF |
| `mask` | NumPy | (H,W) | 0/1 | GeoTIFF |
| `lgp` | NumPy | (H,W) | days | Module I |
| `lgpt5` | NumPy | (H,W) | days | Module I |
| `lgpt10` | NumPy | (H,W) | days | Module I |
| Crop parameters | Excel (.xlsx) | — | various | User |
| Soil water params | NumPy/scalar | — | mm/m, 0–1 | User |

### Crop Parameter Excel Columns

| Column | Unit | Description |
|--------|------|-------------|
| `LAI` | unitless | Leaf Area Index (2–6 typical) |
| `HI` | 0–1 | Harvest Index (fraction of biomass that is yield) |
| `legume` | bool | Nitrogen-fixing crop (affects biomass calc) |
| `adaptability` | 1–4 | Photosynthesis pathway class |
| `min_cycle_length` | days | Minimum crop cycle |
| `max_cycle_length` | days | Maximum crop cycle |
| `height` | meters | Canopy height for kc adjustment |
| `D1` | m/% | Growth stage percentages (D1, D2, D3, D4) |
| `kc` | unitless | Crop coefficients (initial, mid, end) |
| `kc_all` | unitless | Full-cycle crop coefficient |
| `yloss_f` | 0–1 | Yield loss factors per stage (4 values) |
| `yloss_f_all` | 0–1 | Full-cycle yield loss factor |
| `est_yield` | kg/ha | Reference potential yield |
| `D1`, `D2` | meters | Rooting depths |
| `pc` | 0–1 | Soil water depletion fraction |

## Outputs

| Variable | Shape | Unit | Description |
|----------|-------|------|-------------|
| `yield_rain` | (H,W) | kg/ha | Maximum rainfed attainable yield |
| `yield_irr` | (H,W) | kg/ha | Maximum irrigated attainable yield |
| `start_date_rain` | (H,W) | DOY 1–365 | Optimal planting date (rainfed) |
| `start_date_irr` | (H,W) | DOY 1–365 | Optimal planting date (irrigated) |
| `fc1_rain` | (H,W) | 0–1 | Thermal screening factor (rainfed) |
| `fc1_irr` | (H,W) | 0–1 | Thermal screening factor (irrigated) |
| `fc2_rain` | (H,W) | 0–1 | Moisture reduction factor |

## Procedure

### Step 1: Initialize and load data
```python
from pyaez import CropSimulation
sim = CropSimulation.CropSimulation()
sim.setStudyAreaMask(mask, 0)
sim.setLocationTerrainData(lat_min, lat_max, elevation)
sim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, humidity)
```

### Step 2: Set crop parameters
```python
sim.readCropandCropCycleParameters(
    'input_crop_TSUM_parameters_maiz_sugar.xlsx', 'maize')
sim.setSoilWaterParameters(Sa=100*np.ones(mask.shape), pc=0.5)
```

### Step 3: Import LGP from Module I
```python
sim.ImportLGPandLGPT(lgp=lgp, lgpt5=lgpt5, lgpt10=lgpt10)
```

### Step 4: Optional thermal screening
```python
tclimate = sim.getThermalClimate()
frost = sim.AirFrostIndexandPermafrostEvaluation()
sim.setThermalClimateScreening(tclimate, no_t_climate=[2,6,7,8,9,10,11,12])
sim.setPermafrostScreening(permafrost_class=frost[1])
```

### Step 5: Simulate crop cycle
```python
sim.simulateCropCycle(start_doy=1, end_doy=365, step_doy=1, leap_year=False)
# WARNING: This is the slowest step. 365 × H × W iterations.
# With Numba: ~10-30 min for 100×100 grid. Without: hours.
```

### Step 6: Extract results
```python
yield_rain = sim.getEstimatedYieldRainfed()       # kg/ha
yield_irr = sim.getEstimatedYieldIrrigated()       # kg/ha
start_rain = sim.getOptimumCycleStartDateRainfed() # DOY
start_irr = sim.getOptimumCycleStartDateIrrigated()# DOY
fc1 = sim.getThermalReductionFactor()              # (rain, irr)
fc2 = sim.getMoistureReductionFactor()             # rainfed only
```

## Verification

1. **Yield range**: Maize typically 0–15,000 kg/ha; irrigated ≥ rainfed
2. **fc1**: 0 or 1 (binary thermal screening); should not exclude tropical areas for tropical crops
3. **fc2**: 0–1; arid areas should have low fc2, humid areas close to 1.0
4. **Start dates**: Should cluster around wet season onset for rainfed crops
5. **Irrigated yield**: Should be higher than rainfed (no water stress)
6. **Compute time**: If >1 hour for small grid, check Numba installation

## Traps

| Trap | Symptom | Root Cause |
|------|---------|------------|
| All yields = 0 | Wrong crop parameter Excel or missing columns | Check sheet/column names |
| yield_irr < yield_rain | Bug in thermal screening setup | Check fc1 calculation |
| Yields unrealistically high | est_yield in wrong unit (ton instead of kg) | est_yield must be kg/ha |
| Extremely slow execution | Numba not installed/compiled | `pip install numba` |
| Memory error | Grid too large, 365 iterations | Reduce grid or use step_doy > 1 |

## Example

```python
sim = CropSimulation.CropSimulation()
sim.setStudyAreaMask(mask, 0)
sim.setLocationTerrainData(13.87, 22.59, elev)
sim.setMonthlyClimateData(min_temp, max_temp, precip, srad, wind, rhum)
sim.readCropandCropCycleParameters('input_crop_TSUM_parameters_maiz_sugar.xlsx', 'maize')
sim.setSoilWaterParameters(Sa=100*np.ones(mask.shape), pc=0.5)
sim.ImportLGPandLGPT(lgp=lgp, lgpt5=lgpt5, lgpt10=lgpt10)
sim.simulateCropCycle(start_doy=1, end_doy=365, step_doy=1, leap_year=False)
yield_rain = sim.getEstimatedYieldRainfed()
print(f"Mean rainfed yield: {yield_rain[mask>0].mean():.0f} kg/ha")
```
