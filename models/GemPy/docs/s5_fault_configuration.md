# S5: Fault Configuration

## Purpose

Configure fault geometry, fault relations, and fault behavior in the GemPy
model. Faults are one of the most complex aspects of 3D geological modeling
and require careful setup to produce correct structural models.

## Inputs

| Input              | Format    | Source                                |
|--------------------|-----------|---------------------------------------|
| Organized model    | GeoModel  | S3 output                             |
| Fault point data   | CSV       | Surface points on the fault plane     |
| Fault orientations | CSV       | Orientations perpendicular to fault   |
| Fault relations    | matrix    | Which series the fault affects        |

## Outputs

| Output           | Type      | Description                            |
|------------------|-----------|----------------------------------------|
| Faulted model    | GeoModel  | Model with fault geometry configured   |

## Procedure

### Step 1: Prepare fault data

Faults require:
- **At least 2 surface points** defining the fault plane position
- **At least 1 orientation** perpendicular to the fault surface
- Orientations should point in the direction of the hanging wall

```
# In surface_points.csv:
X,Y,Z,formation
1000,500,-200,Main_Fault
1000,1500,-400,Main_Fault

# In orientations.csv:
X,Y,Z,G_x,G_y,G_z,formation
1000,1000,-300,1,0,0,Main_Fault
```

### Step 2: Mark groups as faults

```python
import gempy as gp

# After map_stack_to_surfaces:
gp.set_is_fault(model, ["Fault_Series"])
```

### Step 3: Define fault relations

The fault relation matrix is a boolean `n_groups x n_groups` array where
`matrix[i, j] = True` means "group i (fault) displaces group j".

```python
import numpy as np

# 3 groups: Fault_Series, Upper_Series, Lower_Series
n = 3
fr = np.zeros((n, n), dtype=bool)
fr[0, 1] = True  # Fault displaces Upper_Series
fr[0, 2] = True  # Fault displaces Lower_Series
gp.set_fault_relation(model, fr)
```

**Important**: Fault relations are NOT symmetric (TRAP dt_012).
`fr[0,1]=True` does NOT imply `fr[1,0]=True`.

### Step 4: Multiple faults

For models with multiple faults, consider fault–fault interactions:

```python
# 4 groups: Fault1, Fault2, Strat_Upper, Strat_Lower
fr = np.zeros((4, 4), dtype=bool)
fr[0, 1] = True   # Fault1 offsets Fault2
fr[0, 2] = True   # Fault1 offsets Strat_Upper
fr[0, 3] = True   # Fault1 offsets Strat_Lower
fr[1, 2] = True   # Fault2 offsets Strat_Upper
fr[1, 3] = True   # Fault2 offsets Strat_Lower
gp.set_fault_relation(model, fr)
```

### Step 5: Finite faults (prototype)

For faults with limited extent:

```python
gp.set_is_finite_fault(model, ["Fault_Series"])
```

**Warning**: Finite fault support is a prototype feature in GemPy v3.

## Verification

- [ ] Fault surface points define a planar or curved surface
- [ ] Fault orientations are perpendicular to the fault plane
- [ ] Fault relations matrix correctly maps which series are displaced
- [ ] Fault–fault interactions are geologically consistent
- [ ] Fault does not extend beyond the model extent
- [ ] Offset direction is correct (check polarity of orientations)

## Traps

| Trap    | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| dt_012  | Fault relation missing — fault visible but no offset | silent   |
| dt_004  | Fault orientation polarity wrong — offset reversed   | silent   |

## Example

Two intersecting normal faults in a sedimentary basin:

```python
# Structural mapping
gp.map_stack_to_surfaces(
    gempy_model=model,
    mapping_object={
        "F1": ("Normal_Fault_1",),
        "F2": ("Normal_Fault_2",),
        "Sediments": ("Sand", "Clay", "Limestone"),
        "Basement": ("Granite",)
    }
)

# Mark as faults
gp.set_is_fault(model, ["F1", "F2"])

# F1 is older (cuts everything), F2 is younger (doesn't offset F1)
fr = np.zeros((4, 4), dtype=bool)
fr[0, 1] = True   # F1 offsets F2
fr[0, 2] = True   # F1 offsets Sediments
fr[0, 3] = True   # F1 offsets Basement
fr[1, 2] = True   # F2 offsets Sediments
fr[1, 3] = True   # F2 offsets Basement
gp.set_fault_relation(model, fr)
```
