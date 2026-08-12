# Stage 6: Calibration Guide

## Purpose

Calibrate TOPMODEL parameters against observed streamflow to achieve
acceptable simulation performance. TOPMODEL typically has 4–6 free
parameters that significantly affect discharge prediction.

## Inputs

| Input | Description |
|-------|-------------|
| Observed Q (m³/s) | Daily streamflow at basin outlet |
| Base parameter set | From Stage 3 |
| inputs.dat | Forcing (fixed during calibration) |
| subcat.dat | TWI distribution (fixed during calibration) |

## Outputs

| Output | Description |
|--------|-------------|
| Calibrated params.dat | Optimized parameter set |
| calibration_report.json | NSE, KGE for each trial |

## Calibration Strategy

### Most Sensitive Parameters (calibrate first)

1. **szm** (0.001–0.1 m): Controls recession curve shape.
   - Too small → flashy response, quick recession
   - Too large → slow response, long baseflow tail

2. **t0** (ln(T0), range ~ -1 to 9): Controls total baseflow magnitude. NOTE: t0 is LN-transmissivity (binary: szq=exp(t0+log(dt)-TL)), not linear m/hr.
   - Too small → low baseflow
   - Too large → excessive baseflow

3. **srmax** (0.001–0.5 m): Controls ET partitioning.
   - Too small → too much runoff, not enough ET
   - Too large → too much ET, not enough runoff

### Secondary Parameters

4. **td** (1–100 hr): Unsaturated zone delay.
5. **Q0**: Set from observed baseflow
6. **sr0**: Set to 0 or small value

### Usually Fixed

- **chv, rv**: Channel velocities (affect timing, not volume)
- **infex**: Usually 0 (TOPMODEL assumes saturation excess)
- **xk0, hf, dth**: Only if infex=1

## Procedure

1. **Define objective function**: Maximize NSE or KGE on daily Q.

2. **Set parameter bounds**:
   ```python
   bounds = {
       'szm':   (0.005, 0.08),
       't0':    (-1.0, 9.0),   # ln(T0) scale
       'td':    (5.0, 80.0),
       'srmax': (0.01, 0.2),
   }
   ```

3. **Run parameter sweep or optimization**:
   - Monte Carlo: 1000–5000 random samples
   - Latin Hypercube: better coverage, 500–2000 samples
   - Differential Evolution: efficient optimizer, 100–500 generations

4. **Split period**: Use 60/40 split for calibration/validation.
   - Bengbu: calibrate 1981–1985, validate 1986–1990

5. **Evaluate each run**:
   - Run TOPMODEL
   - Parse output
   - Compute NSE/KGE
   - Record parameter set and metric

6. **Select best**: Highest NSE or KGE.

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Optimizing with wrong units | Converges to wrong minimum | Verify conversions first |
| Over-fitting to peaks | Poor baseflow simulation | Use KGE (includes bias/variability) |
| Parameter equifinality | Many parameter sets give similar NSE | Report ensemble, not single best |
| Calibrating with spinup data | Inflated metrics | Exclude first year |

## Example

```python
import numpy as np

param_names = ['szm', 't0', 'td', 'srmax']
bounds = [(0.005, 0.08), (-1.0, 9.0), (5, 80), (0.01, 0.2)]  # t0 is ln(T0)

best_nse = -999
best_params = None

for trial in range(1000):
    params = {name: np.random.uniform(lo, hi)
              for name, (lo, hi) in zip(param_names, bounds)}
    # Write params.dat, run model, compute NSE
    nse = run_and_evaluate(params)
    if nse > best_nse:
        best_nse = nse
        best_params = params.copy()

print(f"Best NSE: {best_nse:.3f}")
print(f"Best params: {best_params}")
```
