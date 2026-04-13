# Stage 5: Output Parsing and Analysis

## Purpose

Parse DuMux VTK output files into analysis-ready formats (CSV, numpy arrays) and extract key groundwater simulation results: pressure fields, velocity fields, tracer concentrations, and derived quantities like hydraulic head and water balance.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| VTK output files | `.vtu` (unstructured) | DuMux simulation (Stage 4) |
| PVD index file | `.pvd` (XML) | DuMux simulation (Stage 4) |
| Probe point coordinates | user-specified | Monitoring well locations |

## Outputs

| Output | Format | Purpose |
|--------|--------|---------|
| Time series CSV | CSV (time, variables) | Temporal analysis, plotting |
| Spatial field CSV | CSV (x, y, z, variables) | Spatial analysis, GIS |
| Summary statistics | JSON | Validation, reporting |
| Head time series | CSV | Comparison with observed heads |

## Procedure

### Step 1: Identify output files

DuMux generates VTK files named `{ProblemName}-{step:05d}.vtu`:
```bash
ls 1p_*.vtu
# 1p-00000.vtu  1p-00001.vtu  1p-00002.vtu  ...
```

A `.pvd` file indexes all time steps with actual time values:
```xml
<VTKFile type="Collection">
  <Collection>
    <DataSet timestep="0" file="1p-00000.vtu"/>
    <DataSet timestep="100" file="1p-00001.vtu"/>
    <DataSet timestep="500" file="1p-00002.vtu"/>
  </Collection>
</VTKFile>
```

### Step 2: Extract time series at monitoring points

For calibration/validation, extract pressure (or derived head) at specific locations:

```python
# Using parse_dumux_output.py
python tools/parse_dumux_output.py \
    --input_dir output/ \
    --pattern "groundwater*.vtu" \
    --output heads_timeseries.csv \
    --variables pressure \
    --probe_points "500,250;200,100;800,400"
```

### Step 3: Convert pressure to hydraulic head

DuMux outputs pressure in Pa. To compare with observed well data (typically in meters):

```
h [m] = (p [Pa] - p_atm) / (ρ × g) + z [m]
      = (p - 101325) / (1000 × 9.81) + z
      = (p - 101325) / 9810 + z
```

Where z is the elevation of the measurement point.

### Step 4: Extract spatial snapshots

For mapping pressure/head/velocity at a specific time:

```python
python tools/parse_dumux_output.py \
    --input_dir output/ \
    --pattern "groundwater*.vtu" \
    --output spatial_field.csv \
    --variables pressure,velocity \
    --snapshot -1  # last time step
```

### Step 5: Compute derived quantities

**Darcy velocity** (from pressure gradient):
DuMux can output velocity directly if `AddVelocity = true` in `[Vtk]`.

**Water balance**:
```
ΔS = Σ(Recharge) - Σ(Discharge) - Σ(Extraction)
```
Check that the water balance closes (error < 1% of total flux).

**Hydraulic gradient**:
```
i = Δh / ΔL = (h₁ - h₂) / distance
```

### Step 6: Statistical summary

```python
import numpy as np

# Read time series
data = np.loadtxt("heads_timeseries.csv", delimiter=",", skiprows=1)
times = data[:, 0]
heads = data[:, 1:]

# Summary stats
print(f"Head range: {np.min(heads):.2f} – {np.max(heads):.2f} m")
print(f"Head change: {heads[-1] - heads[0]} m over {times[-1]} s")
print(f"Steady-state check: max |dh/dt| = {np.max(np.abs(np.diff(heads, axis=0))):.2e}")
```

## Verification

1. **Pressure range**: Should be positive (absolute pressure). If negative, something is wrong.
2. **Head range**: Should be within physically reasonable bounds for the aquifer (0–1000 m typically).
3. **Velocity magnitude**: Typical groundwater: 1e-9 to 1e-4 m/s. If > 1e-2, check permeability units.
4. **Mass balance**: Compute total in minus total out. Should be < 1% of total flux.
5. **Steady state**: For steady-state runs, check that the final solution changes < 0.1% from the previous time step.

## Traps

### TRAP: VTK precision loss
DuMux defaults to Float32 VTK output. For pressure values around 1e5 Pa, Float32 gives only ~7 significant digits, which is marginal for head computations (±0.001 m accuracy).

**Fix**: Set `[Vtk] Precision = Float64` in the `.input` file.

### TRAP: Cell-centered vs vertex-centered data
CC-TPFA produces cell-centered data. Box scheme produces vertex-centered data. The parsing code must handle both (check `<CellData>` vs `<PointData>` in the VTU file).

**Detection**: Number of data values doesn't match number of cells or number of points.
**Fix**: `parse_dumux_output.py` checks both `cell_data` and `point_data`.

### TRAP: Binary VTK format
DuMux may write VTK in appended binary format (base64-encoded). The pure-Python XML parser in `parse_dumux_output.py` only handles ASCII format. Use `meshio` or `vtk` library for binary files.

**Detection**: `<DataArray>` elements have no text content but `format="appended"` attribute.
**Fix**: Install `meshio` (`pip install meshio`) and use its VTK reader.

### TRAP: Velocity output requires explicit flag
By default, DuMux does NOT output velocity. You must add:
```ini
[Vtk]
AddVelocity = true
```

Without this, `velocity` will not be found in VTK files.

### TRAP: Time values from filenames vs PVD
VTU filenames contain step numbers (00001, 00002, ...), NOT physical time values. The actual simulation time is in the PVD file. Using step numbers as time produces incorrect time series.

**Fix**: Always parse the `.pvd` file for time values when available.

## Example

```bash
# Extract pressure time series at 3 monitoring wells
python tools/parse_dumux_output.py \
    --input_dir build/examples/1ptracer/ \
    --pattern "tracer*.vtu" \
    --output results/tracer_timeseries.csv \
    --variables "x^tracer,pressure" \
    --probe_points "0.5,0.5;0.25,0.75;0.75,0.25"

# Extract final spatial snapshot
python tools/parse_dumux_output.py \
    --input_dir build/examples/1ptracer/ \
    --pattern "1p*.vtu" \
    --output results/pressure_field.csv \
    --variables pressure \
    --snapshot -1
```

### Post-processing with ParaView

```bash
# Open in ParaView (interactive visualization)
paraview output/groundwater.pvd

# ParaView Python script (batch)
from paraview.simple import *
reader = OpenDataFile("groundwater.pvd")
Show(reader)
ColorBy(reader, ("CELLS", "pressure"))
SaveScreenshot("pressure_map.png")
```
