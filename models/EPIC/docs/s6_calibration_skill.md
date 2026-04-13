# Stage 6: Calibration and Parameter Optimization

## Purpose

Calibrate EPIC model parameters against observed yield or biomass data using
optimization algorithms (Particle Swarm Optimization, Differential Evolution)
via the PyGMO library. Calibration adjusts PARM.DAT (global parameters) or
CROPCOM.DAT (crop-specific parameters) to minimize the discrepancy between
simulated and observed crop performance.

## Prerequisites

- Stages 0-5 completed (working simulation with output)
- Observed data (yield, biomass, LAI) for calibration
- PyGMO library installed
- SALib for sensitivity analysis (optional)

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Workspace | config.yml + files | Functioning EPIC workspace |
| Observed data | CSV | Yield/biomass observations per site/year |
| PARM.DAT | Fixed-width | Model parameters to calibrate |
| CROPCOM.DAT | Fixed-width | Crop parameters to calibrate |
| CROPCOM.sens / PARM.sens | CSV | Parameter ranges and sensitivity |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Calibrated PARM.DAT | Fixed-width | Optimized global parameters |
| Calibrated CROPCOM.DAT | Fixed-width | Optimized crop parameters |
| Calibration log | JSON | Optimization history |
| Comparison plot | PNG | Observed vs simulated |

## Procedure

### Step 1: Sensitivity Analysis (optional but recommended)

Identify which parameters most affect yield before calibrating:

```python
from geoEpic.io import Parm
parm = Parm('model/PARM.DAT')

# Load sensitivity ranges
# PARM.sens contains: Parm, Description, Min, Max, Category, Unit, ID
sensitive_params = ['PARM2', 'PARM7', 'PARM8', 'PARM15', 'PARM30']
```

### Step 2: Define Logger and Objective

```python
from geoEpic.core import Workspace
import pandas as pd

ws = Workspace('config.yml')
obs = pd.read_csv('observed_yield.csv')  # SiteID, Year, Yield_obs

@ws.logger
def compute_error(site):
    """Per-site: compute RMSE between simulated and observed yield."""
    from geoEpic.io import ACY
    acy = ACY(f'output/{site.id}.ACY')
    sim = acy.get_var('YLDG')

    # Merge with observations
    merged = sim.merge(obs[obs['SiteID'] == site.id],
                       left_on='YR', right_on='Year')

    rmse = ((merged['YLDG'] - merged['Yield_obs'])**2).mean()**0.5
    return {'rmse': rmse}

@ws.objective
def objective():
    """Aggregate: mean RMSE across all sites."""
    log = ws.fetch_log('compute_error')
    return log['rmse'].mean()
```

### Step 3: Set Sensitive Parameters

```python
from geoEpic.io import Parm

parm = Parm(ws.model.path)
parm.set_sensitive(['PARM2', 'PARM7', 'PARM8'])  # Select params to calibrate
```

### Step 4: Run Optimization

```python
problem = ws.make_problem(parm)

# Using PSO (Particle Swarm Optimization)
import pygmo as pg
algo = pg.algorithm(pg.pso(gen=50))
pop = pg.population(problem, size=20)
pop = algo.evolve(pop)

# Best solution automatically updates PARM.DAT
best_params = pop.champion_x
best_rmse = pop.champion_f
print(f"Best RMSE: {best_rmse}")
```

### Key Calibration Parameters

**PARM.DAT (global, affect all crops):**

| Parameter | Description | Typical Range |
|-----------|-------------|---------------|
| PARM2 | Water stress harvest index | 0.5-1.0 |
| PARM7 | N fixation factor | 0.0-2.0 |
| PARM8 | Soil evaporation coefficient | 1.5-2.5 |
| PARM15 | Runoff CN factor | 0.5-1.5 |
| PARM30 | Soil water routing coefficient | 0.0-1.0 |

**CROPCOM.DAT (per-crop):**

Calibrate development and yield parameters specific to each crop code.

## Verification

1. **Convergence**: Objective function decreases over iterations
2. **Validation**: Test calibrated parameters on held-out years/sites
3. **Physical plausibility**: Parameters remain within physical bounds
4. **Improvement**: RMSE decreases relative to default parameters

## Traps

| Trap | Symptom | Root Cause | Fix |
|------|---------|------------|-----|
| Overfitting | Good on training, bad on validation | Too many params calibrated | Use fewer, most-sensitive params |
| No convergence | Objective doesn't improve | Wrong params or too few iterations | Try different params or more gen |
| All yields identical | Params outside effective range | Bounds too narrow | Widen parameter ranges |
| PyGMO import error | Module not found | Not installed | pip install pygmo |

## Example

```python
# Quick calibration check
from geoEpic.io import Parm
parm = Parm('model/PARM.DAT')
print(f"PARM2 (water stress HI): {parm.get('PARM2')}")
print(f"PARM8 (soil evap coeff): {parm.get('PARM8')}")
```
