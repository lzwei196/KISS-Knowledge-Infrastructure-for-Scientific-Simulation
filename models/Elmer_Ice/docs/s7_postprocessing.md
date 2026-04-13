# S7: Post-Processing

## Purpose

Extract simulation results from Elmer/Ice VTU output files into analyzable
formats (CSV, numpy arrays) for validation, visualization, and comparison
with observations.

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| VTU files | Stage s5 | XML (VTK Unstructured Grid) | Simulation output |
| Observation data | External | CSV / NetCDF | For validation comparison |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `results.csv` | CSV | Nodal values for snapshot analysis |
| `timeseries.csv` | CSV | Time series of domain-averaged statistics |
| Validation plots | PNG | Comparison with observations |

## Procedure

### Extract Single Snapshot

```bash
python parse_vtu_output.py --vtu_file results0010.vtu \
    --variables SSAVelocity,H,Zs,Zb \
    --output snapshot.csv --convert_velocity_to_ma
```

Output CSV columns: `node_id, x, y, z, SSAVelocity_m_per_a, H, Zs, Zb`

### Extract Time Series

```bash
python parse_vtu_output.py --vtu_dir ./run --pattern "results*.vtu" \
    --variables SSAVelocity,H \
    --output timeseries.csv --timeseries --dt_years 1.0 \
    --convert_velocity_to_ma
```

Output CSV columns: `timestep, time_years, SSAVelocity_mean, SSAVelocity_max, SSAVelocity_min, SSAVelocity_std, H_mean, ...`

### ParaView Visualization

For interactive 3D visualization:
1. Open ParaView
2. File → Open → select `results*.vtu`
3. Apply → select variable to display (e.g., SSAVelocity)
4. Use WarpByScalar to exaggerate vertical scale
5. Use Plot Over Line for cross-sections

### Python Visualization

```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("timeseries.csv")
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
ax1.plot(df["time_years"], df["SSAVelocity_mean"])
ax1.set_ylabel("Mean velocity (m/a)")
ax2.plot(df["time_years"], df["H_mean"])
ax2.set_ylabel("Mean thickness (m)")
plt.savefig("evolution.png")
```

## Verification

- Velocity in m/a should be 0.1-10000 for ice sheets (dt_001)
- Ice thickness should be positive everywhere (dt_016)
- No NaN values in output columns
- Time series should show physically meaningful trends:
  - Thinning where SMB < 0
  - Speedup near terminus
  - Steady state reached for diagnostic runs

## Traps

| Trap | ID | Symptom | Fix |
|------|----|---------|-----|
| Velocity in m/s | dt_001 | Values ~1e-8 instead of ~100 | Use --convert_velocity_to_ma |
| Missing variables | — | NaN columns in CSV | Check variable names match VTU content |
| Wrong VTU pattern | — | No files found | Check --pattern matches filenames |
| Parallel VTU files | — | Missing data | Merge partition files first |

## Example

```bash
# Full post-processing workflow
python parse_vtu_output.py --vtu_dir ./run --pattern "results*.vtu" \
    --variables SSAVelocity,H,Zs,Zb --output timeseries.csv \
    --timeseries --dt_years 1.0 --convert_velocity_to_ma

python parse_vtu_output.py --vtu_dir ./run --pattern "results*.vtu" \
    --variables SSAVelocity,H,Zs,Zb --output final_state.csv \
    --convert_velocity_to_ma

echo "Results extracted to timeseries.csv and final_state.csv"
```
