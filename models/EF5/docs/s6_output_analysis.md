# Stage 6: Output Analysis and Validation

## Purpose

Parse EF5 simulation output, compare against observed streamflow, compute hydrologic performance metrics, and generate diagnostic plots for model evaluation.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| EF5 gauge time series | CSV (datetime, Q m³/s) | Simulated streamflow at gauge locations |
| Observed streamflow | CSV (datetime, Q m³/s) | From USGS, GRDC, or local gauge records |
| Gridded outputs (optional) | GeoTIFF | Streamflow, soil moisture, SWE grids |

## Outputs

| Output | Description |
|--------|-------------|
| `comparison.csv` | Merged observed + simulated time series |
| `metrics.json` | Performance metrics (NSE, KGE, PBIAS, R, RMSE) |
| `comparison.png` | Time series comparison plot |
| Grid statistics | Summary statistics of gridded output fields |

## Procedure

### 1. Read EF5 output

EF5 gauge time series format:
```
YYYY/MM/DD HH:UU:SS,value_cms
2009/06/01 00:00:00,15.342
2009/06/01 01:00:00,16.108
```

```python
from tools.parse_ef5_output import read_ef5_timeseries
sim = read_ef5_timeseries("output/gauge_outlet.csv")
print(f"Read {len(sim)} timesteps, Q range: {min(v for _,v in sim):.2f} - {max(v for _,v in sim):.2f} m³/s")
```

### 2. Align with observations

```python
from tools.parse_ef5_output import align_timeseries
times, obs_vals, sim_vals = align_timeseries(sim, obs, tolerance_seconds=1800)
print(f"Matched {len(times)} timesteps")
```

### 3. Compute metrics

```python
from tools.parse_ef5_output import compute_all_metrics
metrics = compute_all_metrics(obs_vals, sim_vals)
```

| Metric | Formula | Perfect | Good | Acceptable |
|--------|---------|---------|------|------------|
| NSE | 1 - Σ(Qobs-Qsim)²/Σ(Qobs-Qmean)² | 1.0 | >0.7 | >0.5 |
| KGE | 1 - √((r-1)²+(α-1)²+(β-1)²) | 1.0 | >0.7 | >0.5 |
| PBIAS | 100×Σ(Qsim-Qobs)/Σ(Qobs) | 0% | <±10% | <±25% |
| R | Pearson correlation | 1.0 | >0.85 | >0.7 |
| RMSE | √(mean((Qobs-Qsim)²)) | 0 | — | — |

### 4. Generate diagnostic plots

```bash
python tools/parse_ef5_output.py \
    --sim output/gauge_outlet.csv \
    --obs /data/obs/outlet.csv \
    --output-dir results/
```

This generates:
- `comparison.csv` — merged time series
- `comparison.png` — observed (black) vs simulated (blue) with metrics box
- `metrics.json` — all metrics in JSON format

### 5. Analyze gridded output

```python
from tools.parse_ef5_output import list_gridded_outputs, extract_grid_stats
grids = list_gridded_outputs("output/")
for g in grids[:5]:
    stats = extract_grid_stats(g)
    print(f"{g.name}: [{stats['min']:.2f}, {stats['max']:.2f}], mean={stats['mean']:.2f}")
```

## Verification

### Metrics sanity checks

```python
# If NSE < -1: something is fundamentally wrong
assert metrics["nse"] > -10, "NSE extremely negative — check units"

# If PBIAS > 100%: simulated volume vastly exceeds observed
if abs(metrics["pbias"]) > 100:
    print("WARNING: Volume bias > 100% — likely unit or parameter issue")

# If R is negative: time series are anti-correlated (wrong timing)
assert metrics["r"] > -0.5, "Negative correlation — check forcing timing"

# Peak flow comparison
obs_peak = np.max(obs_vals)
sim_peak = np.max(sim_vals)
peak_ratio = sim_peak / obs_peak if obs_peak > 0 else float("nan")
print(f"Peak ratio: {peak_ratio:.2f} (1.0 = perfect)")
```

### Visual checks

1. **Timing**: Are simulated peaks aligned with observed peaks?
2. **Recession**: Does the falling limb decay at similar rate?
3. **Baseflow**: Is the simulated baseflow reasonable?
4. **Seasonality**: Is wet/dry season pattern captured?
5. **Volume**: Is total simulated volume close to observed?

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| Observed data in different timezone | Systematic timing offset, low NSE | Align timezones before comparison |
| Observed data in cfs, simulated in cms | Huge bias | Convert: 1 cfs = 0.0283168 cms |
| Missing observed data (NaN gaps) | Inflated error metrics | Filter NaN pairs before computing metrics |
| Warm-up period included in metrics | Poor NSE due to initial conditions | Use TIME_WARMEND or discard first year |
| Daily obs vs hourly sim | Can't align directly | Aggregate sim to daily before comparison |
| Observed data has flat zeros | Artificially good NSE for dry periods | Check gauge rating curve; evaluate wet periods separately |
| Output file is empty | Missing [Execute] or wrong task name | Check control file for typos |

## Example

```bash
# Full analysis pipeline
python tools/parse_ef5_output.py \
    --sim output/gauge_outlet.csv \
    --obs /data/obs/observed_streamflow.csv \
    --output-dir results/ \
    --grid-dir output/

# Output:
# Read 8760 simulated timesteps
# Read 365 observed timesteps
# Aligned: 365 matched timesteps
# --- Performance Metrics ---
#   nse: 0.72
#   kge: 0.68
#   pbias: -12.3%
#   r: 0.88
#   rmse: 15.42
# [OK] Exported 365 records to results/comparison.csv
# [OK] Plot saved to results/comparison.png
```

### Interpreting poor results

| Issue | Likely cause | Next step |
|-------|-------------|-----------|
| NSE < 0 with correct timing | Wrong magnitude → parameter/unit issue | Check forcing units, recalibrate |
| Good NSE but high PBIAS | Timing OK but volume wrong | Adjust WM (water capacity) or KE (PET factor) |
| Low R with correct volume | Timing wrong → forcing issue | Check forcing file temporal alignment |
| Flat hydrograph (no peaks) | Excessive infiltration | Increase IM, decrease FC, check B parameter |
| Flashy with no baseflow | Insufficient interflow | Increase UNDER, adjust LEAKI |
| Negative streamflow | Bug in routing parameters | Check ALPHA, BETA are positive |
