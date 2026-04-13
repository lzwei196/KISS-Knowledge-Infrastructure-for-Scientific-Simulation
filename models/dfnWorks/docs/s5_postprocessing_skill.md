# Stage 5: Post-Processing and Analysis

## Purpose

Extract, analyze, and visualize dfnWorks simulation results. Compute summary statistics, breakthrough curves, effective permeability, flow channeling metrics, and generate publication-quality figures.

## Prerequisites

- Stage 4 (or 4a) completed: transport simulation finished
- matplotlib, numpy, h5py available in Python environment

## Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| partime | Stage 4 | DAT/HDF5 | Particle travel times (seconds) |
| frac_sequence | Stage 4 | DAT/HDF5 | Fracture IDs per particle trajectory |
| graph_flow.hdf5 | Stage 3a | HDF5 | Flow edge properties (graph mode) |
| params.txt | Stage 1 | Text | Network parameters |
| radii_All.dat | Stage 1 | DAT | Fracture radii |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| Breakthrough curve plot | PNG/PDF | Cumulative fraction vs. time |
| Travel time histogram | PNG/PDF | Distribution of travel times |
| Network visualization | VTK/PNG | 3D fracture network with flow |
| Summary statistics | CSV/JSON | Key metrics table |
| Effective permeability | Float (m^2) | Upscaled network permeability |

## Procedure

### Step 1: Load and Summarize Travel Times

```python
import numpy as np
import os

times = np.loadtxt(os.path.join(DFN.jobname, "partime"))

stats = {
    "n_particles": len(times),
    "mean_s": np.mean(times),
    "median_s": np.median(times),
    "std_s": np.std(times),
    "min_s": np.min(times),
    "max_s": np.max(times),
    "cv": np.std(times) / np.mean(times),  # Coefficient of variation
}

# Convert to useful time units
for unit, factor in [("hours", 3600), ("days", 86400), ("years", 3.156e7)]:
    stats[f"median_{unit}"] = stats["median_s"] / factor
```

### Step 2: Compute Breakthrough Curve

```python
sorted_times = np.sort(times)
n = len(sorted_times)
cdf = np.arange(1, n + 1) / n

# Key percentiles
p5 = sorted_times[int(0.05 * n)]   # First 5% arrival
p50 = sorted_times[int(0.50 * n)]  # Median
p95 = sorted_times[int(0.95 * n)]  # 95% arrival

print(f"First arrival (5%): {p5:.1f} s")
print(f"Median arrival:     {p50:.1f} s")
print(f"Late arrival (95%): {p95:.1f} s")
print(f"Tailing ratio (p95/p5): {p95/p5:.1f}")
```

### Step 3: Plot Breakthrough Curve

```python
import matplotlib.pyplot as plt

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

# CDF (breakthrough curve)
ax1.semilogx(sorted_times, cdf, color='#2563EB', linewidth=2)
ax1.set_xlabel("Travel time (s)")
ax1.set_ylabel("Cumulative fraction")
ax1.set_title("Breakthrough Curve")
ax1.axhline(0.5, color='gray', linestyle='--', alpha=0.5)
ax1.grid(True, alpha=0.3)

# PDF (histogram)
ax2.hist(np.log10(times), bins=50, color='#2563EB', alpha=0.7, density=True)
ax2.set_xlabel("log10(Travel time / s)")
ax2.set_ylabel("Density")
ax2.set_title("Travel Time Distribution")
ax2.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("breakthrough_analysis.png", dpi=150)
```

### Step 4: Compute Effective Permeability

```python
# For graph-based flow
# k_eff = Q * mu * L / (A * dP)
# where Q = total flow rate, L = domain length, A = cross-section area, dP = pressure drop

import h5py
with h5py.File(os.path.join(DFN.jobname, "graph_flow.hdf5"), 'r') as hf:
    vol_flow = np.array(hf['vol_flow_rate'])
    Q_total = np.sum(np.abs(vol_flow))  # m^3/s

domain = DFN.params['domainSize']['value']
L = domain[0]                     # Flow direction length (m)
A = domain[1] * domain[2]          # Cross-section area (m^2)
dP = 2e6 - 1e6                     # Pressure drop (Pa)
mu = 8.9e-4                        # Viscosity (Pa.s)

k_eff = Q_total * mu * L / (A * dP)
print(f"Effective permeability: {k_eff:.2e} m^2")
```

### Step 5: Flow Channeling Analysis

```python
# Compute dQ (flow channeling density)
DFN.compute_dQ(G)

# Fraction of flow carried by top 10% of fractures
import h5py
with h5py.File(os.path.join(DFN.jobname, "graph_flow.hdf5"), 'r') as hf:
    flows = np.abs(np.array(hf['vol_flow_rate']))

sorted_flows = np.sort(flows)[::-1]
total_flow = np.sum(sorted_flows)
top10_flow = np.sum(sorted_flows[:int(0.1 * len(sorted_flows))])
channeling_ratio = top10_flow / total_flow
print(f"Top 10% of fractures carry {channeling_ratio*100:.1f}% of flow")
```

## Verification

1. **Breakthrough curve shape**: Should show characteristic power-law tailing for fracture networks
2. **Particle recovery**: >90% of particles should reach the outlet
3. **Tailing ratio**: p95/p5 > 10 is typical for heterogeneous fracture networks
4. **Effective permeability**: Should be between minimum and maximum single-fracture permeability
5. **Flow channeling**: Top 10% carrying >50% of flow is typical

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Travel times in wrong units | Statistics off by orders of magnitude | Graph mode outputs SECONDS; convert explicitly | — |
| Ignoring non-arrived particles | Optimistic breakthrough curve | Report recovery fraction; low recovery = connectivity issue | dt_006 |
| Comparing graph vs full-physics directly | Systematic differences | Graph mode neglects 2D fracture flow; expect ~30% difference | dk_009 |

## Example

```python
# Full post-processing pipeline
import numpy as np
import matplotlib.pyplot as plt
import json

# Load results
times = np.loadtxt(os.path.join(DFN.jobname, "partime"))
sorted_t = np.sort(times)
cdf = np.arange(1, len(sorted_t)+1) / len(sorted_t)

# Summary
summary = {
    "n_particles": int(len(times)),
    "median_travel_time_s": float(np.median(times)),
    "mean_travel_time_s": float(np.mean(times)),
    "recovery_fraction": float(len(times) / 10000),  # if 10000 released
    "tailing_ratio": float(sorted_t[int(0.95*len(sorted_t))] / sorted_t[int(0.05*len(sorted_t))]),
}

with open("simulation_summary.json", "w") as f:
    json.dump(summary, f, indent=2)

print(json.dumps(summary, indent=2))
```
