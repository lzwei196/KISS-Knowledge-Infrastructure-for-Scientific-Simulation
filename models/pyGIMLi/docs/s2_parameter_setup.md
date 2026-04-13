# s2: Parameter Setup — Model Parameterization and Constraints

## Purpose

Define the starting model, parameter bounds, region constraints, and
regularization settings for pyGIMLi inversion. Correct parameterization
prevents inversion divergence and ensures physically meaningful results.

## Inputs

| Input                | Format         | Unit          | Source               |
|----------------------|----------------|---------------|----------------------|
| Inversion mesh       | `.bms` / Mesh  | m             | s1 output            |
| Rock type table      | CSV            | varies        | Geological knowledge |
| Borehole logs        | CSV            | Ω·m or m/s    | Field data           |
| Prior model          | NumPy array    | method-dep.   | Previous inversion   |

## Outputs

| Output               | Format         | Unit          | Destination          |
|----------------------|----------------|---------------|----------------------|
| Region config        | JSON           | method-dep.   | s3 inversion         |
| Starting model       | NumPy array    | method-dep.   | s3 inversion         |
| Transform config     | JSON           | —             | s3 inversion         |

## Procedure

### Step 1: Define regions on mesh
```python
import pygimli as pg

mesh = pg.load("inversion_mesh.bms")

# Regions are defined by cell markers (set during meshing)
# Or assign programmatically:
for cell in mesh.cells():
    if cell.center().y() > -5:
        cell.setMarker(1)   # shallow layer
    elif cell.center().y() > -15:
        cell.setMarker(2)   # intermediate layer
    else:
        cell.setMarker(3)   # deep layer
```

### Step 2: Configure region properties
```python
from pygimli.physics import ert

mgr = ert.ERTManager()
mgr.setMesh(mesh)

# Access region manager
rm = mgr.fop.regionManager()

# Set starting values per region
rm.region(1).setStartModel(100)    # 100 Ohm·m
rm.region(2).setStartModel(500)    # 500 Ohm·m
rm.region(3).setStartModel(1000)   # 1000 Ohm·m

# Set parameter bounds (for TransLogLU)
rm.region(1).setModelTransStr("log")
rm.region(2).setModelTransStr("log")

# Fix a region (do not invert)
rm.region(3).setFixed(True)

# Set single value for a region (one parameter for all cells)
rm.region(1).setSingle(True)
```

### Step 3: Set regularization
```python
# Global regularization strength
mgr.inv.setLambda(20)

# Vertical smoothness weight (< 1 allows more vertical variation)
mgr.inv.setZWeight(0.7)

# Robust data weighting (L1 norm — good for outliers)
mgr.inv.setRobustData(True)

# Block model (minimum-length regularization — sharp boundaries)
mgr.inv.setBlockyModel(True)
```

### Step 4: Set data and model transforms

| Transform     | Use Case                          | Parameters              |
|---------------|-----------------------------------|-------------------------|
| `TransLog`    | Strictly positive quantities      | None                    |
| `TransLogLU`  | Positive with bounds              | lower, upper            |
| `TransCotLU`  | Bounded parameters                | lower, upper            |
| `TransLin`    | Unbounded (travel times)          | None                    |

```python
# Data transform (ERT: log of apparent resistivity)
mgr.inv.dataTrans = pg.trans.TransLogLU()

# Model transform (resistivity: strictly positive)
mgr.fop.modelTrans = pg.trans.TransLog()
```

### Step 5: Generate starting model from petrophysics
```bash
# Using KI tool
python ki/tools/convert_parameters.py \
    --input rock_types.csv \
    --method ert \
    --mode rock_table \
    --lambda-init 20 \
    --z-weight 0.7 \
    --output regions.json
```

## Verification

1. **Starting model plausibility**: values within expected physical range
2. **Bounds**: lower > 0 for log transforms
3. **Region assignment**: each mesh cell has a valid marker
4. **Lambda**: 10–100 for initial run (reduce if underfitting)
5. **zWeight**: 0.2–1.0 (lower → more vertical structure allowed)

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_011 | Inversion diverges | Starting model far from truth | Use homogeneous median of data |
| dt_012 | Negative model values | Linear transform on positive qty | Use TransLog or TransLogLU |
| dt_013 | No depth resolution | zWeight = 1.0 (isotropic) | Reduce to 0.3–0.7 |
| dt_014 | Over-smoothed result | Lambda too high | Reduce lambda by factor 2–5 |
| dt_015 | Artifacts / overfitting | Lambda too low or error too large | Increase lambda, reduce error |

## Example

```python
import pygimli as pg
from pygimli.physics import ert
import json

# Load region config from KI tool
with open("regions.json") as f:
    config = json.load(f)

# Create manager with data
data = ert.load("survey.ohm")
mgr = ert.ERTManager(data)

# Apply region settings
for reg in config["regions"]:
    rid = reg["region_id"]
    rm = mgr.fop.regionManager()
    rm.region(rid).setStartModel(reg["starting_model"])

# Set regularization
mgr.inv.setLambda(config["regularization"]["lambda"])
mgr.inv.setZWeight(config["regularization"]["z_weight"])
```

## Petrophysical Reference

### ERT Resistivity (Ω·m)
| Material      | Min   | Typical | Max     |
|---------------|-------|---------|---------|
| Clay          | 1     | 20      | 100     |
| Sand (wet)    | 50    | 200     | 500     |
| Sand (dry)    | 100   | 1000    | 5000    |
| Gravel        | 100   | 500     | 1000    |
| Limestone     | 100   | 1000    | 10000   |
| Granite       | 1000  | 10000   | 100000  |

### SRT Velocity (m/s)
| Material      | Min   | Typical | Max     |
|---------------|-------|---------|---------|
| Soil          | 100   | 300     | 500     |
| Clay          | 1000  | 1800    | 2500    |
| Sand          | 200   | 800     | 2000    |
| Sandstone     | 1400  | 3000    | 4500    |
| Limestone     | 2000  | 4000    | 6000    |
| Granite       | 4000  | 5500    | 6500    |
