# Stage 6: Output Analysis and Validation

## Purpose

Parse TopoFlow output files, compute hydrologic performance metrics, and
compare simulated results to observations or published values.  This is the
final quality check before accepting model results.

## Inputs

| File                      | Format    | Description                            |
|---------------------------|-----------|----------------------------------------|
| `*_0D-Q.txt`              | Text      | Simulated outlet discharge (m³/s)      |
| `*_0D-d.txt`              | Text      | Simulated outlet depth (m)             |
| `*_2D-Q.nc`               | NetCDF    | Spatiotemporal discharge grids         |
| `*_report.txt`            | Text      | Run summary with peak Q and volumes    |
| Observed discharge file   | CSV/Text  | Gauged Q for comparison                |

## Outputs

| File                      | Format    | Description                            |
|---------------------------|-----------|----------------------------------------|
| `*_hydrograph.csv`        | CSV       | time, Q_sim, depth, velocity           |
| `*_summary.json`          | JSON      | Peak Q, volume, timing, metrics        |
| `*_grid_max_Q.csv`        | CSV       | Max discharge at each grid cell        |
| Validation plot           | PNG       | Obs vs. sim hydrograph with metrics    |

## Procedure

### Step 1: Parse output files

Use `tools/parse_output.py`:

```bash
python ki/tools/parse_output.py \
  --output_dir ./model_output/ \
  --prefix June_20_67 \
  --dt 6.0 \
  --save_dir ./parsed_results/ \
  --observed ./obs_Q.txt
```

### Step 2: Compute performance metrics

| Metric | Formula | Ideal | Interpretation |
|--------|---------|-------|----------------|
| NSE | 1 − Σ(Qobs−Qsim)² / Σ(Qobs−Q̄obs)² | 1.0 | > 0.5 acceptable, > 0.75 good |
| KGE | 1 − √((r−1)² + (α−1)² + (β−1)²) | 1.0 | > 0.5 acceptable |
| PBIAS | 100 × Σ(Qsim−Qobs) / Σ(Qobs) | 0% | ±10% good, ±25% acceptable |
| RMSE | √(mean((Qobs−Qsim)²)) | 0 | Units: m³/s |
| r | Pearson correlation | 1.0 | Linear fit quality |

```python
import numpy as np

def nse(obs, sim):
    return 1 - np.sum((obs - sim)**2) / np.sum((obs - obs.mean())**2)

def kge(obs, sim):
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim.std() / obs.std()
    beta = sim.mean() / obs.mean()
    return 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

def pbias(obs, sim):
    return 100 * np.sum(sim - obs) / np.sum(obs)
```

### Step 3: Create validation plot

```python
import matplotlib.pyplot as plt
import numpy as np

obs = np.loadtxt('obs_Q.txt')
sim = np.loadtxt('June_20_67_0D-Q.txt')
dt = 6.0  # seconds
time_min = np.arange(len(sim)) * dt / 60

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(time_min, obs[:len(sim)], 'k-', linewidth=1.5, label='Observed')
ax.plot(time_min, sim, color='#2563EB', linewidth=1.5, label='TopoFlow')

ax.set_xlabel('Time [min]')
ax.set_ylabel('Discharge [m³/s]')
ax.set_title('TopoFlow Validation — Treynor, IA (June 20, 1967)')
ax.legend()

# Add metrics box
nse_val = nse(obs[:len(sim)], sim)
textstr = f'NSE = {nse_val:.3f}\nPeak Q = {sim.max():.2f} m³/s'
ax.text(0.95, 0.95, textstr, transform=ax.transAxes,
        fontsize=10, verticalalignment='top', horizontalalignment='right',
        bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

plt.tight_layout()
plt.savefig('validation.png', dpi=150)
```

### Step 4: Interpret results

**Hydrograph shape diagnostics:**

| Observation                    | Likely Cause                          | Action                          |
|--------------------------------|---------------------------------------|---------------------------------|
| Sim peak too high              | Too little infiltration or ET         | Increase Ks or θi               |
| Sim peak too low               | Too much infiltration                 | Decrease Ks or verify units     |
| Sim peak too early             | Too-fast routing or low storage       | Increase Manning's n or width   |
| Sim peak too late              | Too-slow routing                      | Decrease Manning's n            |
| No recession limb              | No baseflow or storage                | Enable saturated zone component |
| Negative or NaN values         | Numerical instability                 | Reduce timestep (dt)            |
| Flat line at zero              | No forcing reaching channels          | Check met forcing and D8 grid   |

### Step 5: Sensitivity analysis (optional)

Run multiple scenarios varying key parameters:

| Run | Manning's n | Ks (m/s) | θi   | NSE  | Notes            |
|-----|-------------|----------|------|------|------------------|
| 1   | 0.03        | 3.67e-6  | 0.25 | 0.72 | Baseline         |
| 2   | 0.05        | 3.67e-6  | 0.25 | 0.68 | Delayed peak     |
| 3   | 0.03        | 7.19e-6  | 0.25 | 0.55 | Too much infil.  |
| 4   | 0.03        | 3.67e-6  | 0.40 | 0.78 | Wetter init. cond|

## Verification

1. **Metrics are finite:** NSE, KGE, PBIAS should not be NaN or Inf.
2. **Sim length matches obs:** Interpolate if timesteps differ.
3. **Volume conservation:** Total outflow + infiltration + ET ≈ total precipitation.
4. **Physical plausibility:** Peak Q should be within order of magnitude of drainage area
   × peak rainfall rate.

## Traps

| Trap                              | Symptom                              | Fix                                |
|-----------------------------------|--------------------------------------|------------------------------------|
| Observed and simulated on different time bases | Misaligned metrics | Interpolate to common timestep |
| Comparing m³/s with L/s          | Metrics look terrible                | Convert to same units              |
| Very short simulation             | Recession not captured, poor NSE     | Extend T_stop_model                |
| Baseflow in observed, none in sim | Poor recession NSE                   | Enable satzone or add baseflow     |

## Example

Treynor Iowa — June 20, 1967 storm event:
- Observed peak Q: ~3.5 m³/s
- Time to peak: ~70 minutes
- Event duration: ~250 minutes
- Expected NSE with calibrated parameters: 0.7–0.9
