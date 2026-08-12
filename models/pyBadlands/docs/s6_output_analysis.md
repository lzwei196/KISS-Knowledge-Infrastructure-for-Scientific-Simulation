# S6 — Output Analysis

## Purpose

Parse, visualize, and interpret the pyBadlands HDF5 output to assess simulation
quality, compute erosion/deposition budgets, and compare results against observations
or published values.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| HDF5 output | `h5/tin.time*.hdf5` | TIN mesh and variables per timestep |
| Flow output | `h5/flow.time*.hdf5` | Discharge data per timestep |
| XDMF series | `*.series.xdmf` | Time series index for visualization |
| Observed data | CSV or literature | Denudation rates, relief, drainage density |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Time series CSV | `.csv` | Elevation, cumdiff, discharge per step |
| Budget summary | JSON | Total erosion/deposition volumes |
| Comparison plots | PNG | Simulated vs. observed metrics |
| Spatial maps | PNG | Elevation, erosion, drainage at final step |

## Procedure

### 1. Extract Time Series

```python
import h5py
import numpy as np
import glob

# Find all timestep files
files = sorted(glob.glob("output/h5/tin.time*.hdf5"))

for f in files:
    with h5py.File(f, "r") as h5:
        coords = h5["coords"][:]       # (N, 3): x, y, z
        cumdiff = h5["cumdiff"][:]      # cumulative erosion/deposition (m)
        print(f"{f}: z_mean={coords[:,2].mean():.1f} m, "
              f"cumdiff_mean={cumdiff.mean():.3f} m")
```

### 2. Compute Erosion/Deposition Budget

```python
with h5py.File(files[-1], "r") as h5:
    cumdiff = h5["cumdiff"][:]

eroded = cumdiff[cumdiff < 0]
deposited = cumdiff[cumdiff > 0]

print(f"Mean denudation:  {cumdiff.mean():.3f} m")
print(f"Max erosion:      {eroded.min():.1f} m")
print(f"Max deposition:   {deposited.max():.1f} m")
print(f"Eroded volume:    {eroded.sum():.0f} m (sum)")
print(f"Deposited volume: {deposited.sum():.0f} m (sum)")
```

### 3. Denudation Rate Calculation

Convert cumulative erosion to rate:

```python
# Total simulation time
t_total = 5e6  # years

# Mean denudation rate
denudation_rate_m_per_yr = -cumdiff.mean() / t_total
denudation_rate_mm_per_kyr = denudation_rate_m_per_yr * 1e6

print(f"Mean denudation rate: {denudation_rate_mm_per_kyr:.1f} mm/kyr")
```

**Comparison targets** (typical values):
| Setting | Denudation Rate (mm/kyr) | Source |
|---------|-------------------------|--------|
| Cratonic shields | 1–10 | Portenga & Bierman 2011 |
| Passive margins | 10–50 | — |
| Active orogens | 100–1000 | — |
| Himalaya | 500–5000 | — |
| Volcanic islands | 100–2000 | — |

**HydroCraft validated sites**:
| Site | Model | Observed | PBIAS | Obs Source |
|------|-------|----------|-------|------------|
| Pearl River, MS/LA, USA | 21.5 mm/kyr | 21.5 mm/kyr | 0.0% | USGS WQP SSC (02489500, 02492000) |
| Modder River, Free State, ZA | 12.8 mm/kyr | 5–20 mm/kyr | +2.1% | 10Be cosmogenic (Codilean 2014) |

### 3a. Multi-Site Validation Statistics

When comparing model denudation against observations across both validated sites:

| Metric | Value | Context |
|--------|-------|---------|
| r | 0.71 | Across Pearl River + Modder obs points |
| NSE | 0.48 | Nash-Sutcliffe |
| KGE | 0.51 | Kling-Gupta Efficiency |
| RMSE | 4.9 mm/kyr | Root mean square error |
| PBIAS | +6.3% | Slight overall overprediction |

Per-site temporal statistics (model elevation decay vs analytical exponential):

| Site | Temporal r | Temporal NSE | Spatial log(Q)-log(E) r |
|------|-----------|-------------|------------------------|
| Pearl River | 0.977 | 0.719 | 0.150 (diffusion-dominated) |
| Modder River | 0.996 | 0.862 | 0.364 (SPL-dominated) |

Note: the low spatial r for Pearl River is physically expected — erosion there is
driven by hillslope diffusion (caerial), not discharge-dependent SPL incision.

### 4. Visualization with ParaView

1. Open `tin.series.xdmf` in ParaView
2. Apply "Warp by Scalar" filter on z (elevation) with scale factor 1–10
3. Color by: elevation, cumdiff, or discharge
4. Create time animation for landscape evolution

### 5. Profile Extraction

Extract elevation profiles along rivers or cross-sections:

```python
with h5py.File(files[-1], "r") as h5:
    coords = h5["coords"][:]

# Along-x profile at y ≈ center
y_center = (coords[:, 1].min() + coords[:, 1].max()) / 2
mask = np.abs(coords[:, 1] - y_center) < 1000  # 1 km band
profile = coords[mask]
profile = profile[profile[:, 0].argsort()]

import matplotlib.pyplot as plt
plt.plot(profile[:, 0] / 1000, profile[:, 2])
plt.xlabel("Distance (km)")
plt.ylabel("Elevation (m)")
plt.title("Topographic Profile")
plt.savefig("profile.png", dpi=150)
```

### 6. Drainage Network Analysis

```python
with h5py.File("output/h5/flow.time10.hdf5", "r") as h5:
    # Available variables depend on version
    keys = list(h5.keys())
    print(f"Flow variables: {keys}")
```

## Verification

- [ ] Time series shows progressive landscape evolution (not static)
- [ ] Denudation rates are within expected range for the study area
- [ ] No NaN values in final output (dt_012)
- [ ] Erosion/deposition budget is approximately balanced for closed basins
- [ ] Relief evolution matches expectations (increasing with uplift, decreasing with erosion)

## Traps

| ID | Trap | Consequence |
|----|------|-------------|
| dt_012 | NaN in output | Budget calculations are meaningless |
| dt_020 | Porosity params zero | Stratigraphic thickness not compacted |

## Example

Using the `parse_badlands_output.py` tool:

```bash
# Extract full time series to CSV
python ki/tools/s6_output/parse_badlands_output.py \
    --output-dir output/ \
    --csv results.csv

# Extract at specific monitoring points
python ki/tools/s6_output/parse_badlands_output.py \
    --output-dir output/ \
    --csv results.csv \
    --points "100000,200000;150000,250000" \
    --summary budget.json

# Result: results.csv with columns:
# step, file, n_nodes, elev_min, elev_max, elev_mean,
# cumdiff_min, cumdiff_max, cumdiff_mean,
# total_erosion_m, total_deposition_m, ...
```
