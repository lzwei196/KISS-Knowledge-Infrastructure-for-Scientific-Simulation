# Stage 4: Particle Transport Simulation

## Purpose

Simulate solute transport through the DFN using Lagrangian particle tracking. Particles are released at the inlet boundary and tracked through the fracture network to the outlet, producing breakthrough curves (travel time distributions) that characterize transport behavior.

Two methods available:
1. **DFNTrans** (full-physics): C-based particle tracker on mesh, supports aperture variation, matrix diffusion (TDRW), control planes
2. **Graph transport**: Python-based tracking on intersection graph, fast, supports TDRW

## Prerequisites

### Full-Physics Mode
- Stage 3 completed: flow solution available (PFLOTRAN or FEHM)
- DFNTrans binary compiled
- PTDFN_control.dat configuration file

### Graph Mode
- Stage 3a completed: graph flow solution (G object)

## Inputs

### DFNTrans Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| PTDFN_control.dat | User | Control file | Transport parameters and file paths |
| params.txt | Stage 1 | Text | Network parameters |
| full_mesh.inp | Stage 2 | AVS/UCD | Mesh connectivity |
| full_mesh.stor | Stage 2 | STOR | Storage coefficients |
| darcyvel.dat | Stage 3 | DAT | Darcy velocity field |
| aperture.dat | Stage 1 | DAT | Aperture per fracture (m) |
| Boundary zone | Stage 2 | ZONE | Inlet/outlet boundary nodes |

### Graph Transport Inputs

| Input | Source | Format | Description |
|-------|--------|--------|-------------|
| G (graph) | Stage 3a | NetworkX | Directed graph with flow attributes |
| nparticles | User | int | Number of particles to track |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| partime (or partime.dat) | DAT/HDF5 | Travel time per particle (seconds) |
| frac_sequence | DAT/HDF5 | Fracture IDs visited per particle |
| Breakthrough curve | Derived | Cumulative fraction vs. time |
| Trajectories (optional) | AVS | Particle paths for visualization |

## Procedure

### Option A: DFNTrans (Full-Physics)

```python
DFN.dfn_trans()
```

Control file `PTDFN_control.dat` specifies:
```
param: params.txt
poly: poly_info.dat
inp: full_mesh.inp
stor: full_mesh.stor
boundary: allboundaries.zone

PFLOTRAN_vel: darcyvel.dat
PFLOTRAN_cell: cellinfo.dat
PFLOTRAN_uge: full_mesh_vol_area.uge

in-flow-boundary: 3       # left_w (1=top,2=bot,3=left,4=front,5=right,6=back)
out-flow-boundary: 5       # right_e

aperture: yes
aperture_type: frac
aperture_file: aperture.dat
porosity: 1.0
density: 997.73             # kg/m^3
satur: 1.0

timesteps: 10000000
time_units: seconds
flux_weight: yes
seed: 0

init_nf: yes
init_partn: 10              # 10 particles per inlet fracture edge
```

### Option B: Graph Transport

```python
# Basic transport
DFN.run_graph_transport(G, 10000, "partime", "frac_sequence")

# With TDRW (matrix diffusion)
DFN.run_graph_transport(G, 10000, "partime", "frac_sequence",
                        tdrw_flag=True,
                        matrix_porosity=0.01,
                        matrix_diffusivity=1e-10)  # m^2/s

# With control planes
DFN.run_graph_transport(G, 10000, "partime", "frac_sequence",
                        control_planes=[50, 100, 150, 200],
                        direction="x")
```

### Step 3: Analyze Breakthrough Curve

```python
import numpy as np
import matplotlib.pyplot as plt

times = np.loadtxt("partime")
sorted_t = np.sort(times)
cdf = np.arange(1, len(sorted_t)+1) / len(sorted_t)

plt.semilogx(sorted_t, cdf)
plt.xlabel("Travel time (s)")
plt.ylabel("Cumulative fraction")
plt.title("Breakthrough Curve")
plt.savefig("btc.png")
```

## Verification

1. **Particle recovery**: Most particles (>90%) should reach the outlet
2. **Breakthrough curve shape**: Should show early arrivals (fast paths) and long tail (slow paths)
3. **Median travel time**: Should be physically reasonable for domain size and flow rate
4. **Mass balance**: Number of arrived particles / total particles released
5. **TDRW effect**: Matrix diffusion should increase travel times and broaden the breakthrough curve

### Expected Travel Time Estimate

For a rough check: `t ~ L * phi / v` where:
- L = domain length along flow direction (m)
- phi = porosity (typically 1 for open fractures)
- v = mean velocity from flow solution (m/s)

## Traps

| Trap | Symptom | Fix | Triplet |
|------|---------|-----|---------|
| Wrong boundary numbering | Particles released at wrong face | Check convention: 1=top,2=bot,3=left,4=front,5=right,6=back | dt_008 |
| Flux-weighted particles miss low-flow paths | Biased breakthrough curve | Use init_nf (equal per fracture) for unbiased sampling | dt_016 |
| Time units mismatch | Travel times off by orders of magnitude | Ensure time_units matches expected output | — |
| Diffusivity in cm^2/s instead of m^2/s | TDRW retardation 10000x too high | Multiply by 1e-4 to convert cm^2/s to m^2/s | dt_012 |
| Zero aperture fractures | Particles stuck, infinite travel time | Check aperture.dat for zeros | dt_014 |

## Example

```python
# Complete graph-based transport with analysis
G = DFN.run_graph_flow("left", "right", 2e6, 1e6)
DFN.run_graph_transport(G, 5000, "partime", "frac_sequence")

import numpy as np
times = np.loadtxt(os.path.join(DFN.jobname, "partime"))
print(f"Particles arrived: {len(times)}")
print(f"Median travel time: {np.median(times):.1f} seconds")
print(f"  = {np.median(times)/3600:.1f} hours")
print(f"  = {np.median(times)/86400:.1f} days")
```
