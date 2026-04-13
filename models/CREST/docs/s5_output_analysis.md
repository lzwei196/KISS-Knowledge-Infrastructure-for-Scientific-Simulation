# Stage 5: Output Analysis and Validation

## Purpose

Parse EF5/CREST model outputs, compute hydrological performance metrics, generate validation plots, and assess model adequacy. This stage closes the modeling loop by comparing simulated discharge against observations.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| EF5 output directory | Directory with text/grid files | Stage 4 execution |
| Observed discharge | CSV/TSV with date and Q columns | Gauging station records |
| Simulation metadata | control.txt | For period and gauge info |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Aligned time series | CSV | Date, observed Q, simulated Q |
| Metrics | JSON | NSE, KGE, PBIAS, RMSE, R², R |
| Validation figure | PNG | Observed vs simulated hydrograph with metrics box |

## Procedure

### Step 1: Parse EF5 output files

EF5 writes gauge time series as text files. The format typically contains:
```
YYYY/MM/DD HH:UU:SS  simulated_Q  [observed_Q]
```

```bash
python parse_ef5_output.py \
    --output-dir /data/bengbu/output/ \
    --gauge outlet \
    --obs-file /data/bengbu/obs/discharge.csv \
    --csv-out /data/bengbu/results/timeseries.csv \
    --figure /data/bengbu/results/validation.png \
    --metrics-json /data/bengbu/results/metrics.json \
    --basin-name "Bengbu"
```

### Step 2: Compute performance metrics

| Metric | Formula | Ideal Value | Interpretation |
|--------|---------|-------------|----------------|
| NSE | 1 - Σ(Qo-Qs)²/Σ(Qo-Q̄o)² | 1.0 | >0.5 = satisfactory, >0.65 = good, >0.75 = very good |
| KGE | 1 - √((r-1)²+(α-1)²+(β-1)²) | 1.0 | >0.5 = good, decomposes into correlation, variability, bias |
| PBIAS | 100×Σ(Qs-Qo)/Σ(Qo) | 0% | ±10% = very good, ±25% = satisfactory |
| RMSE | √(mean((Qo-Qs)²)) | 0 | Lower is better, units of m³/s |
| R² | 1 - SS_res/SS_tot | 1.0 | Proportion of variance explained |
| R | Pearson correlation | 1.0 | Timing agreement |

### Step 3: Assess model performance

Performance classification (Moriasi et al., 2007):

| Rating | NSE | PBIAS (%) | RSR |
|--------|-----|-----------|-----|
| Very good | >0.75 | <±10 | <0.50 |
| Good | 0.65-0.75 | ±10-15 | 0.50-0.60 |
| Satisfactory | 0.50-0.65 | ±15-25 | 0.60-0.70 |
| Unsatisfactory | <0.50 | >±25 | >0.70 |

### Step 4: Generate validation figure

The plot shows:
- **Black line**: Observed discharge
- **Blue line (#2563EB)**: Simulated discharge
- **Metrics box**: Top-right with NSE, KGE, PBIAS, R

### Step 5: Diagnose poor performance

If metrics are unsatisfactory, check in order:
1. **Unit errors**: Most common cause of terrible results (NSE < -1)
2. **Forcing quality**: Missing precipitation events
3. **Warm-up period**: Set TIME_WARMEND to skip initial spin-up
4. **Parameter values**: Use CALI_DREAM for automatic calibration
5. **Time step**: May need smaller step for flashy basins
6. **Routing parameters**: COEM/RIVER too high/low causes timing errors

## Verification

1. **Metrics plausibility**: NSE should be > -1 even for uncalibrated runs
2. **Volume balance**: PBIAS should be within ±50% for reasonable setup
3. **Timing**: Check peak timing visually on hydrograph
4. **Base flow**: Ensure recession limb is captured
5. **No flat lines**: Zero discharge usually means forcing or config error

```python
import json
with open("metrics.json") as f:
    m = json.load(f)
assert m["NSE"] > -10, "NSE impossibly low — likely unit error"
assert abs(m["PBIAS"]) < 200, "PBIAS too large — check precipitation units"
```

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Comparing mm/hr to m³/s | NSE = -infinity | Ensure both obs and sim are in same units (m³/s) |
| Wrong observation file format | Empty metrics | Check delimiter (tab vs comma), date column position |
| Time zone offset | Peaks shifted by hours | Align forcing and obs to same timezone |
| Warm-up included in metrics | Poor NSE from initial conditions | Exclude TIME_BEGIN to TIME_WARMEND from metric computation |
| Log-scale comparison for low flows | Poor R² | Use log-transformed metrics for baseflow assessment |
| Missing observations | Fewer aligned pairs than expected | Check observation date format matches EF5 output dates |

## Example

```python
# Quick analysis in Python
import numpy as np

# Load output
sim = np.loadtxt("output/outlet.csv", delimiter=",", skiprows=1, usecols=2)
obs = np.loadtxt("output/outlet.csv", delimiter=",", skiprows=1, usecols=1)

# NSE
nse = 1 - np.sum((obs-sim)**2) / np.sum((obs-np.mean(obs))**2)
print(f"NSE = {nse:.3f}")

# KGE
r = np.corrcoef(obs, sim)[0,1]
alpha = np.std(sim) / np.std(obs)
beta = np.mean(sim) / np.mean(obs)
kge = 1 - np.sqrt((r-1)**2 + (alpha-1)**2 + (beta-1)**2)
print(f"KGE = {kge:.3f}")
```
