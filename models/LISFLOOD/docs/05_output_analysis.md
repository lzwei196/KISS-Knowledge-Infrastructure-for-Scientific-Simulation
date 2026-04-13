# Stage 5: Output Analysis and Validation

## Purpose

Parse LISFLOOD output files (NetCDF maps, TSS time series), compute hydrological performance metrics against observations, and diagnose model behavior. This stage covers post-processing, calibration assessment, and common output interpretation pitfalls.

## Inputs

| Input | Source | Format | Notes |
|-------|--------|--------|-------|
| dis.nc | LISFLOOD output | NetCDF | Discharge at all channel pixels |
| *.tss | LISFLOOD output | ASCII TSS | Discharge at gauge points |
| *.nc | LISFLOOD output | NetCDF | State variables, water balance |
| Observed discharge | Gauge stations | CSV | For validation metrics |
| settings.xml | Model configuration | XML | For metadata extraction |

## Outputs

| Output | Description |
|--------|-------------|
| Discharge CSV | Time series at gauges |
| Metrics JSON | NSE, KGE, PBIAS, R², RMSE |
| Water balance summary | Mass conservation check |
| Validation plots | Observed vs simulated hydrographs |

## Procedure

### 1. Parse Discharge Output

**NetCDF (dis.nc)**:
```python
import netCDF4 as nc
ds = nc.Dataset("out/dis.nc")
discharge = ds["dis"][:]  # shape: (time, lat, lon)
# Extract at gauge point (lat_idx, lon_idx)
q_sim = discharge[:, lat_idx, lon_idx]
```

**TSS format**:
```
Discharge timeseries
2
gauge_1
gauge_2
1   3.456   2.789
2   3.891   3.012
...
```

### 2. Compute Performance Metrics

| Metric | Formula | Good | Acceptable | Poor |
|--------|---------|------|------------|------|
| NSE | 1 - Σ(sim-obs)²/Σ(obs-mean)² | > 0.7 | 0.5-0.7 | < 0.5 |
| KGE | 1 - √[(r-1)²+(α-1)²+(β-1)²] | > 0.7 | 0.5-0.7 | < 0.5 |
| PBIAS | 100 × Σ(sim-obs)/Σ(obs) | |±10%| | |±25%| | |>25%| |
| R² | (Σ(sim-mean_s)(obs-mean_o))² / ... | > 0.7 | 0.5-0.7 | < 0.5 |
| RMSE | √(mean((sim-obs)²)) | context | dependent | — |

### 3. Water Balance Check

LISFLOOD writes a total water balance residual in `twb.nc`. The residual should be near zero:
- |TWB| < 1 mm/year: excellent mass conservation
- |TWB| < 10 mm/year: acceptable
- |TWB| > 10 mm/year: investigate water balance closure

### 4. State Variable Diagnostics

| Variable | Expected Range | If Outside Range |
|----------|---------------|------------------|
| theta (soil moisture) | 0.1-0.5 m³/m³ | Too dry or too wet |
| snowcov (SWE) | 0-2000 mm | Check SnowMeltCoef |
| uz (upper zone) | 0-100 mm | Check UpperZoneTimeConstant |
| lz (lower zone) | 0-500 mm | Check GwPercValue, LZThreshold |

## Verification

- [ ] NSE > 0.5 for calibration period (minimum acceptable)
- [ ] KGE > 0.5 for calibration period
- [ ] |PBIAS| < 25% (systematic bias check)
- [ ] Water balance residual < 10 mm/year
- [ ] Peak flows captured within ±20% timing and magnitude
- [ ] Baseflow recession matches observed
- [ ] Snow dynamics reasonable for basin latitude/elevation

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| dt_014 | **silent** | SnowMeltCoef too high — snow melts immediately, no accumulation |
| dt_015 | **silent** | GwLoss drains all groundwater — baseflow goes to zero |
| dt_016 | **silent** | b_Xinanjiang near 0 — all rain becomes immediate runoff (flashy) |
| dt_018 | **silent** | writeNetcdf off — no spatial output to analyze |
| — | **silent** | Comparing 6-hourly simulation to daily observations without averaging |

## Calibration Strategy

LISFLOOD calibration typically follows this priority:

1. **Baseflow** first: `LowerZoneTimeConstant`, `GwPercValue`, `GwLoss`
2. **Quick flow**: `UpperZoneTimeConstant`, `b_Xinanjiang`, `PowerPrefFlow`
3. **Snow basins**: `SnowMeltCoef`
4. **Routing**: `CalChanMan` (channel speed)
5. **Lakes/reservoirs**: `LakeMultiplier`, `adjust_Normal_Flood`

Use split-sample validation: calibrate on period A, validate on period B.

## Example

```bash
# Parse output and compute metrics
python tools/parse_output.py \
    --output_dir /data/lisflood/out \
    --settings /data/lisflood/settings/warm.xml \
    --obs_file /data/observed/discharge.csv \
    --obs_col "Q_m3s" \
    --csv_out /data/results/simulated_q.csv \
    --summary /data/results/metrics.json

# Quick validation plot
python -c "
import pandas as pd
import matplotlib.pyplot as plt
obs = pd.read_csv('observed/discharge.csv', index_col=0, parse_dates=True)
sim = pd.read_csv('results/simulated_q.csv', index_col=0)
fig, ax = plt.subplots(figsize=(12,4))
ax.plot(obs.index, obs['Q_m3s'], 'k-', label='Observed', linewidth=0.8)
ax.plot(sim.index[:len(obs)], sim.iloc[:len(obs),0], color='#2563EB', label='Simulated')
ax.set_ylabel('Discharge [m³/s]')
ax.legend()
plt.savefig('validation.png', dpi=150, bbox_inches='tight')
"
```
