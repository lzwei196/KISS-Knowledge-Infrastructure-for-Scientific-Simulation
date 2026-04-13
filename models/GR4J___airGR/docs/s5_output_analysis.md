# Stage 5: Output Analysis and Validation

## Purpose

Parse GR4J model outputs, compute efficiency metrics against observed discharge, create diagnostic plots, and assess model performance. This stage serves both for post-calibration evaluation and for independent validation periods.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| GR4J output CSV | Stage 3/4 output | CSV | Qsim_mm, Prod, Rout, etc. |
| Forcing CSV with Qobs | Stage 1 output | CSV | Qobs_mm column |
| Catchment info | Stage 2 output | JSON | For conversion to m3/s |

## Outputs

| Output | Format | Content |
|--------|--------|---------|
| Metrics JSON | JSON | NSE, KGE, PBIAS, RMSE, R2, obs/sim means |
| Validation plot | PNG | Precipitation + hydrograph (obs black, sim blue) |
| Summary CSV | CSV | Merged observed/simulated time series |

## Procedure

### Step 1: Read and merge outputs

Merge GR4J output (Qsim) with observed discharge (Qobs) on Date column.

### Step 2: Compute efficiency metrics

| Metric | Formula | Perfect Value | Interpretation |
|--------|---------|---------------|----------------|
| NSE | 1 - SS_res/SS_tot | 1.0 | > 0.75 good, < 0 worse than mean |
| KGE | 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2) | 1.0 | Balanced: correlation + variability + bias |
| PBIAS | 100 * sum(sim-obs) / sum(obs) | 0% | Positive = overestimation |
| RMSE | sqrt(mean((obs-sim)^2)) | 0.0 | Absolute error in mm/d |
| R2 | r_pearson^2 | 1.0 | Linear correlation |

### Step 3: Create validation plot

Standard validation figure with two panels:
1. **Top panel**: Precipitation (inverted bars, blue)
2. **Bottom panel**: Discharge hydrograph
   - Observed: black line
   - Simulated: #2563EB blue line
   - Metrics box in top-right corner

### Step 4: Diagnose performance issues

Common patterns and their causes:

| Pattern | Likely Cause | Fix |
|---------|-------------|-----|
| Sim << Obs (low flows) | Precip too low, PE too high | Check unit conversions |
| Sim >> Obs (high flows) | Precip too high | Check aggregation |
| Timing offset | X4 wrong, warmup too short | Re-calibrate, extend warmup |
| Poor baseflow | X3 too small | Increase X3 range |
| Flat response | X1 too large (absorbs all rain) | Reduce X1 |
| Negative X2 | Water loss to deep GW | Normal for karst, check geology |

### Step 5: Convert to physical units (optional)

For reporting or comparison:
```
Q_m3s = Qsim_mm * area_km2 / 86.4
Q_ls  = Q_m3s * 1000
Volume_Mm3 = Qsim_mm * area_km2 * 1e-3  # per day
```

## Verification

1. **Metrics in expected range**: NSE > 0.5 for calibration, > 0.4 for validation
2. **Water balance**: Annual P ≈ Annual (AE + Q ± Exchange)
3. **Seasonal pattern**: Sim should track seasonal obs pattern
4. **Flow duration curve**: Compare exceedance probabilities

## Traps

| ID | Trap | Silent? | Detection |
|----|------|---------|-----------|
| OUT-001 | Qsim all zero | Yes | Check forcing data |
| OUT-002 | NSE = -infinity | Yes | Qobs unit mismatch |
| OUT-003 | PBIAS > 100% | Warning | Major volume error |
| OUT-004 | Comparing wrong periods | Semi | Date mismatch in merge |
| OUT-005 | Ignoring warmup in metrics | Semi | Include only run period |

## Example

```python
from tools.parse_gr4j_output import parse_gr4j_output

result = parse_gr4j_output(
    output_csv="gr4j_output.csv",
    forcing_csv="forcing_gr4j.csv",
    qobs_column="Qobs_mm",
    metrics_json="metrics.json",
    plot_png="validation.png",
    catchment_name="Bengbu (Huai River)",
)
# result["metrics"]["NSE"] ≈ 0.90
# result["metrics"]["KGE"] ≈ 0.85
```

## Performance Benchmarks (GR4J Literature)

| Study | Catchments | Median NSE (Cal) | Median NSE (Val) |
|-------|-----------|-------------------|-------------------|
| Perrin et al. (2003) | 429 France | 0.89 | 0.85 |
| Coron et al. (2012) | 1131 Australia | 0.80 | 0.70 |
| Zhang et al. (2015) | 31 China | 0.85 | 0.78 |

## Advanced Analysis

### Split-sample test
```
Period A (cal): 1990-1999
Period B (val): 2000-2009
Compare NSE_cal vs NSE_val
Robust model: |NSE_cal - NSE_val| < 0.1
```

### Differential split-sample test
```
Wet period calibration → validate on dry period (and vice versa)
Tests model robustness under non-stationary conditions
```

### Internal diagnostics
- Plot production store level (Prod) vs time: should cycle seasonally
- Plot routing store level (Rout) vs time: should respond to storms
- Plot actual exchange (AExch) vs time: indicates GW interaction
