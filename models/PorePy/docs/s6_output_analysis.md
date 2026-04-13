# S6: Output Parsing and Analysis

## Purpose

Extract, parse, and analyze PorePy simulation results stored in VTU/VTK format.
Convert results to CSV for comparison with observations, plotting, and metric
computation.

## Inputs

| Input              | Type            | Description                             |
|--------------------|-----------------|-----------------------------------------|
| VTU files          | `.vtu`          | Per-subdomain simulation results        |
| PVD file           | `.pvd`          | Time series collection file             |
| Output folder      | directory       | Contains all VTU/PVD files              |

## Outputs

| Output             | Type            | Description                             |
|--------------------|-----------------|-----------------------------------------|
| CSV data           | `.csv`          | Tabular results for analysis            |
| Time series        | `.csv`          | Variable evolution at specific points   |
| Spatial fields     | `.csv`          | Snapshot of all cells at one time step  |

## Procedure

### Step 1: Locate output files

PorePy writes to `model_params["folder_name"]`:

```
porepy_output/
├── results_sd_0.vtu          # Matrix grid data
├── results_sd_1.vtu          # Fracture grid data (if any)
├── results_intf_0.vtu        # Interface data
├── results.pvd               # Time series collection
└── solver_statistics.json    # Convergence data
```

### Step 2: Parse with tool

```bash
# Parse all VTU files in output directory
python ki/tools/parse_porepy_output.py \
    --input-dir porepy_output/ \
    --output results.csv

# Parse time series from PVD
python ki/tools/parse_porepy_output.py \
    --pvd-file porepy_output/results.pvd \
    --variables pressure,displacement \
    --output timeseries.csv

# Parse single snapshot
python ki/tools/parse_porepy_output.py \
    --vtu-file porepy_output/results_sd_0.vtu \
    --output snapshot.csv
```

### Step 3: Load and analyze in Python

```python
import pandas as pd
import numpy as np

# Load parsed CSV
df = pd.read_csv("results.csv")

# Pressure statistics
print(f"Pressure range: {df['pressure'].min():.2e} to {df['pressure'].max():.2e} Pa")
print(f"Mean pressure: {df['pressure'].mean():.2e} Pa")

# Time series at a specific cell
cell_data = df[df['cell_id'] == 0]
plt.plot(cell_data['timestep_s'] / 86400, cell_data['pressure'] / 1e6)
plt.xlabel('Time (days)')
plt.ylabel('Pressure (MPa)')
```

### Step 4: Compute metrics

```python
# Compare with observations
obs = pd.read_csv("observations.csv")
sim = pd.read_csv("results.csv")

# Merge on location/time
merged = pd.merge(obs, sim, on=['cell_id', 'timestep_s'])

# Nash-Sutcliffe Efficiency
obs_vals = merged['pressure_obs'].values
sim_vals = merged['pressure'].values
nse = 1 - np.sum((obs_vals - sim_vals)**2) / np.sum((obs_vals - obs_vals.mean())**2)
print(f"NSE: {nse:.3f}")

# RMSE
rmse = np.sqrt(np.mean((obs_vals - sim_vals)**2))
print(f"RMSE: {rmse:.2e} Pa")

# PBIAS
pbias = 100 * np.sum(sim_vals - obs_vals) / np.sum(obs_vals)
print(f"PBIAS: {pbias:.1f}%")
```

### Step 5: Visualize in ParaView

1. Open `results.pvd` in ParaView
2. Apply "Warp by Vector" for displacement visualization
3. Use "Threshold" filter to isolate fracture subdomains
4. Use "Plot Over Line" for 1D profiles

## Verification

- CSV record count matches expected: n_cells × n_timesteps
- No NaN values in extracted data
- Pressure/temperature within physical bounds
- Time monotonically increasing

## Traps

| ID     | Trap                                         | Consequence                              |
|--------|----------------------------------------------|------------------------------------------|
| dt_016 | VTU file missing expected variables          | Empty columns in CSV                     |
| dt_002 | Results in scaled units, not SI              | Wrong metric values if assumed Pa        |
| dt_013 | NaN values from diverged simulation          | Metrics return NaN                       |

## Example

```python
import numpy as np
import matplotlib.pyplot as plt

# Quick visualization of pressure field
import csv

with open("results.csv") as f:
    reader = csv.DictReader(f)
    pressures = [float(row["pressure"]) for row in reader if "pressure" in row]

if pressures:
    print(f"Extracted {len(pressures)} pressure values")
    print(f"Range: {min(pressures):.2e} to {max(pressures):.2e} Pa")
    plt.hist(pressures, bins=50)
    plt.xlabel("Pressure (Pa)")
    plt.ylabel("Count")
    plt.title("Pressure Distribution")
    plt.savefig("pressure_histogram.png", dpi=150)
```
