# Stage 6: Output Analysis

## Purpose

Parse RAPID output NetCDF files to extract discharge and volume time series,
compute hydrological performance metrics against observations, and generate
visualization plots for model evaluation.

## Inputs

| Input | Format | Units | Source |
|-------|--------|-------|--------|
| Qout.nc | NetCDF4 | m³/s | RAPID output (Stage 5) |
| V.nc (optional) | NetCDF4 | m³ | RAPID output (Stage 5) |
| Qobs.nc (optional) | NetCDF4 | m³/s | Observed gage data |
| Reach ID(s) | Integer | — | User-specified gage locations |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| results.csv | CSV | Time series: time, simulated, observed |
| metrics.json | JSON | NSE, KGE, PBIAS, RMSE, r |
| hydrograph.png | PNG | Discharge plot with metrics |

## Procedure

1. **Extract discharge** at specific reach IDs:
   ```python
   import netCDF4 as nc
   ds = nc.Dataset("Qout.nc")
   riv_ids = ds["rivid"][:]
   idx = np.where(riv_ids == target_reach_id)[0][0]
   q_sim = ds["Qout"][:, idx]  # m³/s time series
   ```

2. **Load observations** if available (same NetCDF format or CSV).

3. **Align time series**: Match simulated and observed by timestamp. Handle:
   - Different start/end dates
   - Missing values (NaN)
   - Different time steps (aggregate simulated to daily if needed)

4. **Compute metrics**:

   | Metric | Formula | Perfect | Good Range |
   |--------|---------|---------|------------|
   | NSE | 1 - Σ(obs-sim)² / Σ(obs-mean)² | 1.0 | > 0.5 |
   | KGE | 1 - √((r-1)² + (α-1)² + (β-1)²) | 1.0 | > 0.5 |
   | PBIAS | 100 × Σ(sim-obs) / Σ(obs) | 0% | ±25% |
   | RMSE | √(mean((obs-sim)²)) | 0 | < σ_obs |
   | r | Pearson correlation | 1.0 | > 0.7 |

5. **Generate hydrograph plot**:
   - Black line: observed discharge
   - Blue (#2563EB) line: simulated discharge
   - Metrics annotation box in upper right
   - X-axis: time (formatted dates)
   - Y-axis: discharge (m³/s)

## Verification

```bash
# Check CSV output
head -5 results.csv
wc -l results.csv

# Check metrics
python3 -c "
import json
m = json.load(open('metrics.json'))
print(f'NSE = {m[\"metrics\"][\"nse\"]:.3f}')
print(f'KGE = {m[\"metrics\"][\"kge\"]:.3f}')
print(f'PBIAS = {m[\"metrics\"][\"pbias\"]:.1f}%')
"

# Verify figure exists
ls -la hydrograph.png
```

## Traps

| Trap | Severity | Description |
|------|----------|-------------|
| Time alignment error | SILENT | Off-by-one in time → metrics are wrong but not obviously so |
| Unit mismatch obs vs sim | SILENT | If Qobs in cfs instead of m³/s → metrics are nonsensical |
| Missing reach in output | DEGRADED | Requested reach_id not in Qout rivid dimension |
| All-zero simulation | SILENT | Indicates Vlat was zero (dt_001) — NSE will be very negative |
| NaN in metrics | DEGRADED | Constant observation or simulation → division by zero |

## Example

```python
# Quick analysis at a gage
import netCDF4 as nc
import numpy as np

ds = nc.Dataset("Qout.nc")
rids = ds["rivid"][:]
q = ds["Qout"][:]

# Find outlet (highest mean discharge)
mean_q = q.mean(axis=0)
outlet_idx = np.argmax(mean_q)
print(f"Outlet reach {rids[outlet_idx]}: mean Q = {mean_q[outlet_idx]:.2f} m³/s")
print(f"Peak Q = {q[:, outlet_idx].max():.2f} m³/s")

ds.close()
```

## Interpretation Guide

| NSE Range | Interpretation |
|-----------|---------------|
| > 0.75 | Very good |
| 0.50–0.75 | Good |
| 0.25–0.50 | Satisfactory |
| < 0.25 | Unsatisfactory |

| PBIAS Range | Interpretation |
|-------------|---------------|
| ±10% | Very good |
| ±10–25% | Good |
| ±25–50% | Satisfactory |
| > ±50% | Unsatisfactory |
