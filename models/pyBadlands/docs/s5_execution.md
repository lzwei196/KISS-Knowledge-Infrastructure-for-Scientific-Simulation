# S5 — Model Execution

## Purpose

Execute the pyBadlands model with a validated XML configuration and monitor the
simulation for errors, instabilities, and performance issues.

## Inputs

| Input | Format | Description |
|-------|--------|-------------|
| XML config | `.xml` file | Complete pyBadlands configuration |
| DEM | raster/CSV | Elevation data referenced by XML |
| Forcing files | CSV/raster | Rainfall, tectonic, sea-level files |
| Output directory | folder | Must exist before run (dt_009) |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| HDF5 time series | `h5/tin.time*.hdf5` | TIN mesh + elevation at each step |
| Flow data | `h5/flow.time*.hdf5` | Discharge, flow direction |
| Strata data | `h5/sed.time*.hdf5` | Stratigraphic layers |
| XDMF files | `xmf/*.xmf` | Visualization metadata |
| Series descriptors | `*.series.xdmf` | Time series index |

## Procedure

### 1. Pre-flight Checks

Before executing, verify:

```bash
# Check XML is well-formed
python -c "import xml.etree.ElementTree as ET; ET.parse('input.xml'); print('XML OK')"

# Check all referenced files exist
grep -oP '(?<=<demfile>|<map>|<curve>|<ufile>|<dfile>)[^<]+' input.xml | \
    while read f; do test -f "$f" || echo "MISSING: $f"; done

# Create output directory
mkdir -p output
```

### 2. Execution

**Python API** (recommended):
```python
from badlands.model import Model

model = Model()
model.load_xml("input.xml", verbose=True)
model.run_to_time(5000000)  # Run to 5 Myr
```

**Using wrapper tool**:
```bash
python ki/tools/s5_run/run_badlands.py --xml input.xml --end 5000000 --verbose
```

**Segmented execution** (for monitoring):
```python
model = Model()
model.load_xml("input.xml")

# Run in stages
for t in range(100000, 5000001, 100000):
    model.run_to_time(t)
    print(f"Time: {model.tNow}, Step: {model.outputStep}")
```

### 3. Monitoring

**Signs of trouble during execution**:

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| Very slow progress | Too fine resolution or too small maxdt | Increase resfactor or maxdt |
| NaN in output | Kd too high or maxdt too large | Reduce Kd or maxdt (dt_016) |
| No erosion at all | Kd too low or no rainfall | Check SPLero and precipitation |
| Extreme elevation changes | Wrong units in forcing | Check all unit conversions |
| Crash at first output | Output directory missing | `mkdir -p output` (dt_009) |

### 4. Restart from Checkpoint

If a simulation is interrupted, restart from a checkpoint:

```xml
<time>
    <start>0</start>
    <end>5000000</end>
    <display>50000</display>
    <restart>
        <rfolder>output</rfolder>
        <rstep>50</rstep>  <!-- Resume from step 50 -->
    </restart>
</time>
```

### 5. Performance Guidelines

| Domain Size | Resolution | Typical Runtime | Memory |
|-------------|-----------|-----------------|--------|
| 100 × 100 km | 1 km | Minutes | < 1 GB |
| 500 × 500 km | 1 km | 10–60 min | 2–4 GB |
| 1000 × 1000 km | 5 km | Minutes | < 1 GB |
| 100 × 100 km | 100 m | Hours | 4–16 GB |

Runtime scales roughly as O(N log N) where N is the number of TIN nodes.

## Verification

- [ ] Simulation completed without errors
- [ ] Output HDF5 files exist in `output/h5/`
- [ ] Expected number of output steps matches `(end - start) / display`
- [ ] No NaN values in final elevation
- [ ] Elevation changes are physically reasonable (< 10 km total change for most cases)
- [ ] Series XDMF files are generated for visualization

## Traps

| ID | Trap | Consequence |
|----|------|-------------|
| dt_009 | Output folder missing | Silent crash |
| dt_012 | NaN propagation | Model produces garbage output |
| dt_016 | Timestep too large | Numerical instability |
| dt_018 | numpy >= 2 | Import errors in Fortran extensions |

## Example

Full execution with monitoring:

```python
import time
from badlands.model import Model

model = Model()
model.load_xml("input.xml", verbose=True)

t0 = time.time()
model.run_to_time(5000000)
elapsed = time.time() - t0

print(f"Completed in {elapsed:.1f}s, {model.outputStep} output steps")
```
