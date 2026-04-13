# Stage 5: Output Parsing — Extracting Results from VTU/PVD

## Purpose

Extract simulation results from OGS VTU output files into analyzable formats (CSV time series, spatial statistics, visualization). OGS output is in VTK format — this stage bridges the gap to standard analysis workflows.

## Inputs

- `result.pvd` — PVD collection file (XML index of timesteps → VTU files)
- `result_ts_*_t_*.vtu` — Individual VTU files per output timestep
- Point locations or regions of interest for time series extraction

## Outputs

- `timeseries.csv` — Time series at specified observation points
- `spatial_stats.csv` — Domain-wide statistics per timestep
- Summary JSON with variable ranges and metadata

## Procedure

### Step 1: Understand VTU file structure

Each VTU file contains:
- **Points**: Node coordinates (x, y, z in meters)
- **Cells**: Element connectivity (triangles, quads, tets, hexes)
- **PointData**: Node-based fields (pressure, temperature, displacement)
- **CellData**: Element-based fields (velocity, stress, MaterialIDs)

**Output file naming convention**:
```
{prefix}_ts_{timestep_number}_t_{time_in_seconds}.vtu
```
Example: `result_ts_10_t_864000.000000.vtu` = timestep 10, time = 864000 s (10 days)

### Step 2: Parse PVD collection file

The PVD file links timesteps to VTU files:
```xml
<?xml version="1.0"?>
<VTKFile type="Collection">
  <Collection>
    <DataSet timestep="0" file="result_ts_0_t_0.000000.vtu"/>
    <DataSet timestep="86400" file="result_ts_1_t_86400.000000.vtu"/>
    <DataSet timestep="172800" file="result_ts_2_t_172800.000000.vtu"/>
  </Collection>
</VTKFile>
```

### Step 3: Extract point time series

Use the tool:
```bash
python tools/parse_ogs_output.py \
  --pvd_file results/result.pvd \
  --variables pressure,v \
  --point "50.0,25.0" \
  --output results/timeseries.csv
```

This produces:
```csv
time_s,time_days,pressure,v_magnitude,v_x,v_y
0,0.0,0.0,0.0,0.0,0.0
86400,1.0,49050.0,1.23e-8,0.0,-1.23e-8
172800,2.0,49050.0,1.23e-8,0.0,-1.23e-8
```

### Step 4: Extract spatial statistics

For domain-wide analysis (min/max/mean per timestep):
```bash
python tools/parse_ogs_output.py \
  --pvd_file results/result.pvd \
  --variables pressure \
  --stats \
  --output results/spatial_stats.csv
```

### Step 5: Convert units for reporting

Remember OGS output is in SI. Common back-conversions:
- Pressure (Pa) → hydraulic head (m): `h = p / (998.2 × 9.81)`
- Temperature (K) → °C: `T_C = T_K - 273.15`
- Time (s) → days: `t_days = t_s / 86400`
- Velocity (m/s) → m/day: `v_day = v_s × 86400`
- Stress (Pa) → MPa: `σ_MPa = σ_Pa / 1e6`

### Step 6: Visualization with Python

```python
import meshio
import matplotlib.pyplot as plt
import numpy as np

# Read final timestep
mesh = meshio.read("result_ts_365_t_31536000.vtu")
pressure = mesh.point_data["pressure"]
coords = mesh.points

# Plot pressure field
plt.tricontourf(coords[:, 0], coords[:, 1], pressure, levels=20)
plt.colorbar(label="Pressure (Pa)")
plt.xlabel("x (m)")
plt.ylabel("y (m)")
plt.title("Pressure Distribution")
plt.savefig("pressure_field.png", dpi=150)
```

## Verification

- [ ] PVD file lists all expected timesteps
- [ ] VTU files are non-empty and parseable
- [ ] Variable names match what was requested in `<output><variables>`
- [ ] Value ranges are physically reasonable (see unit trap table)
- [ ] Time series shows expected temporal behavior

## Traps

| Trap | Consequence | Prevention |
|------|-------------|------------|
| Variable not in output config | Missing from VTU | Add to `<variables>` in `<output>` |
| VTU in binary/appended format | Simple XML parser fails | Use meshio or vtk library |
| Vector variable has 3 components | Single value extraction fails | Extract magnitude or components |
| Large VTU files (3D, fine mesh) | Memory issues during parsing | Process one timestep at a time |
| Compressed VTU (zlib) | Manual XML parsing fails | Use meshio or vtk library |
| Time in filename != actual time | Rounding artifacts | Parse from PVD timestep attribute |

## Example

Extracting hydraulic head at an observation well:

```bash
# Extract pressure at well location (x=50, y=25)
python tools/parse_ogs_output.py \
  --pvd_file results/result.pvd \
  --variables pressure \
  --point "50.0,25.0" \
  --output results/well_pressure.csv

# Convert pressure to head in post-processing
python -c "
import pandas as pd
df = pd.read_csv('results/well_pressure.csv')
df['head_m'] = df['pressure'] / (998.2 * 9.81)
df['time_days'] = df['time_s'] / 86400
df.to_csv('results/well_head.csv', index=False)
print(df.head())
"
```
