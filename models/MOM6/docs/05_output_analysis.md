# Stage 5: Output Analysis and Validation

## Purpose

Parse MOM6 diagnostic output, extract key ocean variables, compute domain-averaged
timeseries, and validate against observations or reanalysis. This stage closes the
simulation pipeline by quantifying model skill.

## Inputs

| File                | Format     | Description                          |
|---------------------|------------|--------------------------------------|
| `ocean_daily.nc`    | NetCDF     | Daily-averaged model diagnostics     |
| `ocean_month.nc`    | NetCDF     | Monthly-averaged model diagnostics   |
| `ocean.stats`       | ASCII text | Per-timestep global statistics       |
| Observations (opt.) | NetCDF/CSV | In-situ or satellite observations    |

### Common Observation Sources

| Source            | Variable | Resolution     | Access                      |
|-------------------|----------|----------------|-----------------------------|
| OISST             | SST      | 0.25° daily    | NOAA NCEI                   |
| Argo profiles     | T, S     | Point, ~10-day | Argo GDAC                   |
| AVISO/CMEMS       | SSH, ADT | 0.25° daily    | Copernicus Marine Service   |
| WOA18             | T, S     | 0.25° monthly  | NOAA NCEI                   |
| OSCAR             | u, v     | 1/3° 5-day     | NASA PO.DAAC                |
| RAPID/MOCHA       | AMOC     | 26.5°N daily   | RAPID project               |

## Outputs

| File                    | Format | Description                         |
|-------------------------|--------|-------------------------------------|
| `mom6_timeseries.csv`   | CSV    | Domain-averaged variable timeseries |
| `mom6_timeseries_stats.csv` | CSV | Energy, CFL, sea level from ocean.stats |
| `validation_report.json`| JSON   | Metrics, bounds checks, warnings   |
| Validation figures      | PNG    | Comparison plots                    |

## Procedure

1. **Parse diagnostics**:
   ```bash
   python output_parser.py ./run_dir \
     --output timeseries.csv \
     --variables SST SSS ssh MLD_003 KE \
     --json-report validation.json
   ```

2. **Regional subsetting** (e.g., North Atlantic):
   ```bash
   python output_parser.py ./run_dir \
     --output north_atlantic.csv \
     --lat-range 20 65 --lon-range -80 0 \
     --variables SST SSS
   ```

3. **Compare against observations**:
   ```bash
   python output_parser.py ./run_dir \
     --output comparison.csv \
     --obs-file OISST_2020.nc --obs-var sst \
     --json-report metrics.json
   ```

4. **Key metrics to compute**:

   | Metric | Formula | Good Value | Description |
   |--------|---------|------------|-------------|
   | RMSE   | √(mean((sim-obs)²)) | < 1.0 degC (SST) | Root mean square error |
   | Bias   | mean(sim-obs) | |bias| < 0.5 degC | Systematic offset |
   | R      | corr(sim, obs) | > 0.90 | Temporal correlation |
   | NSE    | 1 - SS_res/SS_tot | > 0.7 | Nash-Sutcliffe efficiency |
   | PBIAS  | 100×Σ(sim-obs)/Σobs | |PBIAS| < 10% | Percent bias |

## Verification

- [ ] All extracted variables within physical bounds (see SKILL.md §11)
- [ ] No persistent NaN regions in output fields
- [ ] Energy timeseries is stable (not exponentially growing)
- [ ] Sea level statistics are reasonable (|mean SL| < 1 m)
- [ ] CFL remained below 0.8 throughout simulation
- [ ] SST RMSE < 2.0 degC compared to OISST (global, annual mean)
- [ ] SSH RMSE < 0.15 m compared to AVISO (mesoscale resolution)

## Traps

| Trap ID | Symptom                    | Cause                         | Fix                         |
|---------|----------------------------|-------------------------------|-----------------------------|
| -       | All output values are 0    | Diagnostic not registered     | Check diag_table field names |
| -       | Output file is empty       | Time averaging reduces to nothing | Check time bounds in diag_table |
| -       | Discontinuity at restart   | Restart misaligned with averaging period | Align RESTINT with output freq |
| -       | SST bias > 5 degC          | Forcing sign convention error | Review Stage 2 heat flux signs |
| -       | Salinity drift             | Freshwater budget imbalanced  | Check precip-evap closure   |

## Example

```python
from output_parser import validate_input, extract_timeseries, compute_metrics
import numpy as np

# Parse model output
info = validate_input("./run_dir")
ts = extract_timeseries(info["diag_files"], ["SST", "SSS", "ssh"])

# Print summary statistics
for var, data in ts.items():
    means = np.array(data["mean"])
    print(f"{var}: mean={np.nanmean(means):.3f}, "
          f"std={np.nanstd(means):.3f}, "
          f"range=[{np.nanmin(means):.3f}, {np.nanmax(means):.3f}]")

# Compare to observations
obs = np.loadtxt("oisst_monthly.csv", delimiter=",", skiprows=1, usecols=1)
sim = np.array(ts["SST"]["mean"])
metrics = compute_metrics(sim[:len(obs)], obs[:len(sim)])
print(f"SST validation: RMSE={metrics['rmse']:.2f} degC, R={metrics['r']:.3f}, "
      f"NSE={metrics['nse']:.3f}")
```

### Visualization

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Load timeseries
ts = extract_timeseries(info["diag_files"], ["SST"])
time = np.array(ts["SST"]["time"])
sst_sim = np.array(ts["SST"]["mean"])

fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(time, sst_sim, color="#2563EB", linewidth=1.5, label="MOM6")
# ax.plot(time_obs, sst_obs, color="black", linewidth=1.5, label="OISST")
ax.set_xlabel("Time [days]")
ax.set_ylabel("SST [degC]")
ax.set_title("Sea Surface Temperature — MOM6 vs Observations")
ax.legend()

# Add metrics box
# textstr = f"RMSE = {metrics['rmse']:.2f} degC\nR = {metrics['r']:.3f}"
# ax.text(0.97, 0.95, textstr, transform=ax.transAxes, fontsize=10,
#         verticalalignment='top', horizontalalignment='right',
#         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

fig.tight_layout()
fig.savefig("sst_validation.png", dpi=150)
print("Saved sst_validation.png")
```
