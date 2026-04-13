# S3: Structural Organization

## Purpose

Organize geological surfaces into structural groups (series) with correct
stratigraphic relationships (erosion, onlap) and fault configurations.
This step defines how formations interact during interpolation.

## Inputs

| Input              | Format    | Source                           |
|--------------------|-----------|----------------------------------|
| Initialized model  | GeoModel  | S2 output                        |
| Structural config  | JSON/dict | Geological knowledge             |

## Outputs

| Output            | Type      | Description                           |
|-------------------|-----------|---------------------------------------|
| Organized model   | GeoModel  | Model with structural frame configured|

## Procedure

### Step 1: Define structural mapping

Map surfaces to series/groups. The **order of groups matters** — younger
(upper) groups erode older (lower) groups.

```python
import gempy as gp

gp.map_stack_to_surfaces(
    gempy_model=model,
    mapping_object={
        "Fault_Series": ("Main_Fault",),         # Faults first
        "Young_Series": ("Alluvium", "Gravel"),   # Youngest strat
        "Old_Series":   ("Sandstone", "Shale", "Basement")  # Oldest
    }
)
```

### Step 2: Configure fault relations

Mark fault groups and define which series each fault affects.

```python
# Mark as fault
gp.set_is_fault(model, ["Fault_Series"])

# Define fault relationships (which groups the fault cuts)
# Boolean matrix: [fault_i affects group_j]
import numpy as np
fr = np.zeros((3, 3), dtype=bool)
fr[0, 1] = True  # Fault_Series affects Young_Series
fr[0, 2] = True  # Fault_Series affects Old_Series
gp.set_fault_relation(model, fr)
```

### Step 3: Set structural relation type

Each group has a relation type controlling surface interactions:

| Type   | Behavior                                          |
|--------|---------------------------------------------------|
| ERODE  | Younger surfaces truncate older ones (default)    |
| ONLAP  | Younger surfaces terminate against older ones      |
| FAULT  | Surface acts as a fault plane                      |

```python
# Groups are ERODE by default. To set ONLAP:
group = model.structural_frame.get_group_by_name("Young_Series")
group.structural_relation = gp.data.StackRelationType.ONLAP
```

### Step 4: Validate using the parameter builder tool

```bash
python ki/tools/build_structural_params.py \
    --config structural_config.json \
    --surface-points gempy_input/surface_points.csv \
    --validate-only
```

## Verification

- [ ] All formations assigned to a structural group
- [ ] Fault groups marked with `set_is_fault()`
- [ ] Fault relations matrix correctly specifies which groups faults affect
- [ ] Group ordering matches geological history (youngest first)
- [ ] No orphan surfaces (in data but not in any group)
- [ ] ERODE/ONLAP relations match geological intent

## Traps

| Trap    | Description                                          | Severity |
|---------|------------------------------------------------------|----------|
| dt_011  | Wrong group order — impossible erosion patterns       | silent   |
| dt_012  | Fault relation missing — fault doesn't cut layers     | silent   |

## Example

Perth Basin with two faults and three stratigraphic series:

```python
gp.map_stack_to_surfaces(
    gempy_model=model,
    mapping_object={
        "Fault1": ("Darling_Fault",),
        "Fault2": ("Harvey_Fault",),
        "Mesozoic": ("Leederville", "South_Perth"),
        "Paleozoic": ("Cattamarra", "Yarragadee"),
        "Basement": ("Precambrian",)
    }
)
gp.set_is_fault(model, ["Fault1", "Fault2"])

# Faults cut all stratigraphic series
fr = np.zeros((5, 5), dtype=bool)
fr[0, 2:] = True  # Fault1 cuts Mesozoic, Paleozoic, Basement
fr[1, 2:] = True  # Fault2 cuts Mesozoic, Paleozoic, Basement
gp.set_fault_relation(model, fr)
```
