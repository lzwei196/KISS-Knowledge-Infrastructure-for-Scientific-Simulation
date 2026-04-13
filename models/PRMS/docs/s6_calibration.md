# Stage 6: Calibration

## Purpose

Adjust PRMS model parameters to improve agreement between simulated and observed streamflow. PRMS has many adjustable parameters; focus on the most sensitive ones.

## Inputs

- Baseline PRMS setup (control, parameter, data files) from Stages 1-4
- Observed streamflow time series
- Baseline simulation results from Stage 5

## Outputs

- Calibrated parameter file
- Improved performance metrics (NSE, KGE, PBIAS)

## Procedure

### Step 1: Identify calibration parameters

PRMS parameters ranked by sensitivity for streamflow simulation:

| Priority | Parameter | Range | Controls |
|----------|-----------|-------|----------|
| 1 | soil_moist_max | 1-20 in | Total runoff volume |
| 2 | gwflow_coef | 0.001-0.5 | Baseflow recession |
| 3 | slowcoef_lin | 0.001-0.5 | Interflow timing |
| 4 | smidx_coef | 0.001-0.06 | Surface runoff magnitude |
| 5 | smidx_exp | 0.1-0.5 | Surface runoff nonlinearity |
| 6 | ssr2gw_rate | 0.001-0.5 | GW recharge rate |
| 7 | soil_rechr_max | 0.5-10 in | ET and recharge |
| 8 | fastcoef_lin | 0.001-1.0 | Preferential flow |
| 9 | tmax_allsnow | 28-36 F | Snow/rain partitioning |
| 10 | gwstor_init | 0-10 in | Initial GW storage |

### Step 2: Split-sample approach

1. **Calibration period**: First 60-70% of the simulation period
2. **Validation period**: Remaining 30-40%
3. **Warmup**: 1 year before calibration period (exclude from metrics)

### Step 3: Manual calibration strategy

**Phase A — Volume correction** (target: PBIAS < 10%):
1. Adjust `soil_moist_max` → controls total runoff volume
2. If PBIAS > 0 (over-prediction): increase soil_moist_max
3. If PBIAS < 0 (under-prediction): decrease soil_moist_max

**Phase B — Baseflow** (target: baseflow matches low-flow periods):
1. Adjust `gwflow_coef` → recession rate of baseflow
2. Lower values = slower recession = higher baseflow
3. Adjust `ssr2gw_rate` → fraction reaching groundwater

**Phase C — Peak flows** (target: peak magnitude and timing):
1. Adjust `smidx_coef` and `smidx_exp` → surface runoff generation
2. Higher smidx_coef = more runoff per unit soil moisture
3. Adjust `slowcoef_lin` → interflow contribution to peaks

**Phase D — Snow processes** (for snow-dominated basins):
1. Adjust `tmax_allsnow` (default 32F) → snow/rain transition
2. Adjust `rad_trncf` → radiation transmission through canopy
3. Adjust `cecn_coef` → convection-condensation energy coefficient

### Step 4: Automated calibration (optional)

Use external calibration tools:
- **LUCA** (Let Us CAlibrate): USGS tool designed for PRMS
- **PEST**: Model-independent parameter estimation
- **scipy.optimize**: Python-based optimization

### Step 5: Validate

Run model with calibrated parameters on the validation period.
Compute NSE, KGE, PBIAS on validation period only.

## Verification

- [ ] All calibrated parameters within physical bounds
- [ ] NSE > 0.5 on both calibration and validation periods
- [ ] PBIAS < 25% on validation period
- [ ] No degradation of validation metrics vs calibration
- [ ] Water balance closes (ppt ≈ et + runoff + storage change)

## Traps

### 1. Overfitting

Calibrating too many parameters simultaneously can lead to equifinality (many parameter sets fit equally well but for wrong reasons). Start with sensitive parameters only.

### 2. Compensating errors

High soil_moist_max + high gwflow_coef can compensate each other. Always check that individual flow components (surface runoff, interflow, baseflow) are reasonable.

### 3. Snow calibration requires observed SWE

Without observed SWE data, snow parameter calibration is poorly constrained. Use satellite snow cover data as an additional constraint.

### 4. Temperature unit confusion during calibration

If adjusting `tmax_allsnow`, remember it's in the same units as the input temperature (Fahrenheit if temp_units=0). The default 32F = 0C is physically meaningful.

## Example

```python
# Simple manual calibration loop
import subprocess, json

base_params = {"soil_moist_max": 6.0, "gwflow_coef": 0.015, "smidx_coef": 0.005}

# Try different parameter values
for smm in [4.0, 6.0, 8.0, 10.0]:
    for gwc in [0.005, 0.015, 0.05, 0.1]:
        # Update parameter file
        update_param("prms.params", "soil_moist_max", smm)
        update_param("prms.params", "gwflow_coef", gwc)
        # Run PRMS
        subprocess.run(["./prms_hpc", "-C/prms/control"])
        # Compute metrics
        nse = compute_nse_from_output("/prms/output")
        print(f"smm={smm}, gwc={gwc}, NSE={nse:.3f}")
```
