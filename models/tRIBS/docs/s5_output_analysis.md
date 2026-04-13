# S5: Output Analysis and Validation

## Purpose

Parse tRIBS output files into analyzable formats, compute performance metrics,
and validate model results against observed data. This stage determines whether
the simulation is physically reasonable and identifies calibration needs.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| Pixel files (`.pixel`) | Space-delimited | Per-node time series (50+ columns) |
| Outlet file (`.qout`) | Space-delimited | Discharge at outlet |
| Mean response (`.mrf`) | Space-delimited | Basin-averaged water balance |
| Observed discharge | CSV | Measured streamflow for validation |
| Observed soil moisture (optional) | CSV | In-situ or remote sensing data |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Parsed CSV files | CSV | Clean, labeled time series |
| Performance metrics | JSON | NSE, KGE, PBIAS, R², RMSE |
| Validation figures | PNG | Observed vs simulated plots |
| Water balance summary | JSON/CSV | Closure check |

## Procedure

### Step 1: Parse output files to CSV
```bash
python parse_tribs_output.py \
    --input /path/to/output/ \
    --output /path/to/results/ \
    --format all
```

### Step 2: Extract key variables
For discharge validation, extract from outlet file:
```python
import csv
with open("results/outlet_discharge.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        time_hr = float(row["Time_hr"])
        q_m3s = float(row["Discharge_m3s"])
```

### Step 3: Compute performance metrics

**Nash-Sutcliffe Efficiency (NSE):**
```
NSE = 1 - Σ(Qobs - Qsim)² / Σ(Qobs - Qobs_mean)²
```
- NSE = 1: perfect match
- NSE = 0: model is as good as using the mean
- NSE < 0: model is worse than the mean

**Kling-Gupta Efficiency (KGE):**
```
KGE = 1 - sqrt((r-1)² + (α-1)² + (β-1)²)
```
where r = correlation, α = variability ratio, β = bias ratio.
- KGE > 0.5: generally acceptable
- KGE > 0.7: good

**Percent Bias (PBIAS):**
```
PBIAS = 100 × Σ(Qobs - Qsim) / Σ(Qobs)
```
- PBIAS = 0: no bias
- PBIAS > 0: model underestimates
- PBIAS < 0: model overestimates

**Root Mean Square Error (RMSE):**
```
RMSE = sqrt(Σ(Qobs - Qsim)² / n)
```

### Step 4: Check water balance closure
```
P = ET + Q + ΔS
```
where P = precipitation, ET = evapotranspiration, Q = total runoff,
ΔS = change in storage (soil moisture + groundwater).

Water balance error should be < 1% of total precipitation.

### Step 5: Create validation figures
Plot observed vs simulated discharge:
- Observed in black
- Simulated in #2563EB (blue)
- Add metrics box in top-right corner
- Include x-axis label (Date), y-axis label (Discharge, m³/s)

### Step 6: Diagnose issues
If metrics are poor, check the diagnostic triplets for common causes:

| NSE < 0 | Check | Likely cause |
|---------|-------|--------------|
| Peak timing off | STREAM_KSE, HILLSLOPE_KSE | Routing velocity |
| Peak magnitude wrong | Ks, ThetaS | Infiltration |
| Baseflow too low | DEPTHTOBEDROCK, OPTGROUNDWATER | Storage |
| ET too high | OPTEVAP, LAI | ET parameters |
| Everything wrong | Unit conversions | See trap table |

## Verification

- [ ] Water balance closes within 1% of precipitation
- [ ] Discharge values are non-negative
- [ ] No NaN values in parsed output
- [ ] Peak discharge timing is physically reasonable
- [ ] Baseflow recession matches observed pattern
- [ ] ET is within regional expected range (300–1200 mm/yr)
- [ ] Soil moisture stays within 0–porosity bounds

## Traps

| Symptom | Likely Cause | Diagnostic |
|---------|-------------|------------|
| Discharge is 24× too high | Rainfall in mm/day instead of mm/hr | Check rain input units |
| No baseflow | Bedrock depth too shallow (in m instead of mm) | dt_005 |
| Discharge is zero | Ks too high (in m/s instead of mm/hr) or no rain reaching soil | dt_006 |
| ET > Rainfall | RH in % instead of fraction, or T in K | dt_003, dt_002 |
| Water balance doesn't close | Numerical instability or output parsing error | Check time step |
| Hydrograph shape wrong | Manning's n, channel geometry | Calibrate routing |

## Example

```python
import numpy as np

# Load data
obs = np.loadtxt("observed_q.csv", delimiter=",", skiprows=1, usecols=1)
sim = np.loadtxt("results/outlet_discharge.csv", delimiter=",", skiprows=1, usecols=1)

# NSE
nse = 1 - np.sum((obs - sim)**2) / np.sum((obs - np.mean(obs))**2)

# KGE
r = np.corrcoef(obs, sim)[0, 1]
alpha = np.std(sim) / np.std(obs)
beta = np.mean(sim) / np.mean(obs)
kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

# PBIAS
pbias = 100 * np.sum(obs - sim) / np.sum(obs)

print(f"NSE={nse:.3f}  KGE={kge:.3f}  PBIAS={pbias:.1f}%")
```
