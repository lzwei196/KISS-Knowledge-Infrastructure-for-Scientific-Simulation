# EPIC0810 Stage 5 — Calibration & Validation

## Purpose
Compare model-predicted yields, ET, and water balance against independent
observations (FAOSTAT yields, FLUXNET ET, USGS streamflow, SPAM gridded yield).

## Inputs
- Workspace with completed model run
- Observation dataset matching the run year range and location

## Outputs
- Validation metrics: NSE, KGE, PBIAS, RMSE, Pearson r
- Side-by-side time series figure
- Water balance check: |P − ET − Q − ΔS| / P < 5%

## Procedure
```python
from tools.parse_epic_output import parse_ann, water_balance_summary
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance

wb = water_balance_summary("/tmp/epic_run1", "umstead_0")
prcp = wb.get("PRCP(mm)", [])
et = wb.get("ET(mm)", [])
q = wb.get("Q(mm)", [])

# Per-year water balance closure
import numpy as np
P, ET, Q = np.array(prcp), np.array(et), np.array(q)
res = validate_water_balance(P.sum(), ET.sum(), Q.sum(),
                             period_days=365 * len(P))
print(res)

# If observed yields are available
obs = [4.2, 5.0, 4.8, 5.3]    # t/ha for 4 years
sim = [4.5, 4.9, 5.1, 5.0]
print(all_metrics(np.array(obs), np.array(sim)))
```

## Verification
- NSE > 0.5 indicates a usable simulation
- |PBIAS| < 25% for crop yields, < 20% for streamflow
- KGE > 0.5
- Water balance closure error < 5% of P

## Calibration parameters worth touching
| File | Parameter | Effect |
|------|-----------|--------|
| `PARM1102.DAT` row 1–5 | Erosion / runoff coefficients | runoff Q |
| `PARM1102.DAT` row 20–30 | N/P cycling | N stress, denitrification |
| `PARM1102.DAT` row 34 | Heat-unit scheduling | crop maturity |
| `CROPCOM.DAT` HI | Harvest index | yield |
| `CROPCOM.DAT` WA | Radiation use efficiency | biomass |
| `CROPCOM.DAT` DMLA | Maximum LAI | LAI peak |

## Traps
- **Wrong PHU** — if planting OPV1 (potential heat units) doesn't match the actual
  crop, the crop never matures or matures too early. PHU should be computed from
  the local accumulated GDD between planting and maturity.
- **Single-year metrics** — annual yield comparisons need ≥ 5 years to be
  meaningful given climate variability.
- **Calibrating to a single observation network** — overfits to that station
  type. Use multi-source observations (FAOSTAT + SPAM + flux tower).

## Example
```python
import numpy as np
from ki_tools_common.metrics import all_metrics
sim_yield = np.array([4.5, 5.1, 4.9, 5.2, 5.3])
obs_yield = np.array([4.2, 5.0, 4.8, 5.3, 5.0])
print(all_metrics(obs_yield, sim_yield))
# {'nse': 0.78, 'kge': 0.81, 'pbias': -1.2, 'rmse': 0.21, 'r': 0.92}
```
