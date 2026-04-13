# Stage 5: Calibration — Parameter Optimization

## Purpose

Calibrate CWatM parameters to match observed streamflow data. CWatM provides 11 primary calibration parameters that control snow, soil, groundwater, routing, and water body processes.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| Observed discharge | GRDC / local | CSV | Daily/monthly streamflow at gauge |
| Base settings file | Stage 0 | INI | Reference configuration |
| Parameter ranges | Literature / expert | Table | Min/max for each parameter |
| CWatM model | Stage 3 | Python | Working model installation |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Calibrated parameters | INI / JSON | Optimized parameter values |
| Performance metrics | JSON | NSE, KGE per parameter set |
| Sensitivity analysis | CSV / plots | Parameter importance ranking |
| Calibrated settings.ini | INI | Ready-to-use configuration |

## Procedure

### 1. Select Calibration Parameters

CWatM's 11 calibration parameters in priority order:

| Parameter | Key | Range | Process |
|-----------|-----|-------|---------|
| Snow melt coefficient | SnowMeltCoef | 0.001-0.01 | Snow dynamics |
| Crop correction | crop_correct | 0.8-1.5 | Evapotranspiration |
| Soil depth factor | soildepth_factor | 0.5-2.0 | Soil storage |
| Arno beta | arnoBeta_add | 0.01-1.0 | Direct runoff |
| Interflow factor | factor_interflow | 0.5-10.0 | Subsurface flow |
| Recession coefficient | recessionCoeff_factor | 1.0-10.0 | Baseflow |
| Manning's n | manningsN | 0.5-5.0 | Flow velocity |
| Preferential flow | preferentialFlowConstant | 1.0-10.0 | Bypass flow |
| Normal storage limit | normalStorageLimit | 0.1-0.9 | Reservoirs |
| Lake A factor | lakeAFactor | 0.1-1.0 | Lake outflow |
| Lake evaporation | lakeEvaFactor | 0.8-2.0 | Lake ET |

### 2. Choose Calibration Method

CWatM supports several calibration approaches:

**a) Manual calibration** (recommended first):
- Start with default parameters
- Adjust one parameter at a time
- Focus on: crop_correct → soildepth_factor → arnoBeta_add → recessionCoeff_factor

**b) DEAP evolutionary algorithm** (Tutorial 09):
```python
from deap import algorithms, base, creator, tools
# See Tutorials/09_Calibration/calibration_single.py
```

**c) FAST sensitivity analysis** (Tutorial 09):
```python
# Fourier Amplitude Sensitivity Testing
# Identifies most sensitive parameters for a given basin
```

**d) Custom optimization** using `mainwarm()`:
```python
from cwatm.run_cwatm import main, mainwarm

# First run: loads and caches meteorological data
settings = "settings.ini"
args = ["-v"]
meteo, success, last_dis = main(settings, args)

# Subsequent runs: reuses cached meteo (much faster)
def objective(params):
    update_settings(settings, params)
    success, last_dis = mainwarm(settings, args, meteo)
    return compute_nse(last_dis, observed)
```

### 3. Calibration Strategy

**Phase 1: Water balance** (monthly scale)
- Adjust `crop_correct` to match annual ET/runoff ratio
- Adjust `soildepth_factor` to match seasonal storage

**Phase 2: Flow dynamics** (daily scale)
- Adjust `arnoBeta_add` to match peak flows
- Adjust `recessionCoeff_factor` to match recession limbs
- Adjust `factor_interflow` to match intermediate flow

**Phase 3: Snow and routing** (if applicable)
- Adjust `SnowMeltCoef` to match spring snowmelt peaks
- Adjust `manningsN` to match flood wave timing

**Phase 4: Water bodies** (if lakes/reservoirs present)
- Adjust `normalStorageLimit` for reservoir operations
- Adjust `lakeAFactor` and `lakeEvaFactor` for lake dynamics

### 4. Validation

- **Split-sample**: Calibrate on period 1, validate on period 2
- **Proxy-basin**: Calibrate on gauged basin, apply to ungauged neighbor
- **Multi-objective**: Optimize NSE and PBIAS simultaneously

## Verification

- Calibrated NSE should be > 0.5 for well-gauged basins
- Parameters should be within physical ranges
- Seasonal cycle should be captured (timing and magnitude)
- Water balance should close (PBIAS < ±15%)
- Validation period performance should be within 0.1 of calibration

## Traps

1. **Over-fitting**: Too many parameters relative to data length. Use at most 6-8 parameters for daily calibration, 3-4 for monthly.

2. **Equifinality**: Multiple parameter sets give similar NSE. Report uncertainty ranges, not just best fit.

3. **SpinUp contamination**: If SpinUp period is too short, initial conditions affect calibration. Use ≥ 3 year SpinUp.

4. **Local optima**: Evolutionary algorithms may find local optima. Run multiple times with different seeds.

5. **compensation errors**: Wrong `crop_correct` (too high ET) compensated by wrong `arnoBeta_add` (too high direct runoff). Check individual components, not just total discharge.

6. **mainwarm() memory**: Cached meteorological data stays in memory. For global runs, this can be many GB.

## Example

```python
# Simple manual calibration workflow
import numpy as np

# Parameter sets to test
param_grid = {
    "crop_correct": [0.9, 1.0, 1.1, 1.2],
    "soildepth_factor": [0.8, 1.0, 1.2, 1.5],
    "arnoBeta_add": [0.1, 0.2, 0.3, 0.5],
    "recessionCoeff_factor": [3.0, 5.0, 7.0, 10.0],
}

best_nse = -999
best_params = {}

for cc in param_grid["crop_correct"]:
    for sf in param_grid["soildepth_factor"]:
        # Update settings file
        update_calibration_params(settings_path, {
            "crop_correct": cc,
            "soildepth_factor": sf,
        })
        # Run model
        success, last_dis = mainwarm(settings, args, meteo)
        # Compute metric
        nse = compute_nse(last_dis, observed)
        if nse > best_nse:
            best_nse = nse
            best_params = {"crop_correct": cc, "soildepth_factor": sf}

print(f"Best NSE: {best_nse:.3f}, Params: {best_params}")
```
