# S2: Compliance Check

## Purpose

Validate that a model's BMI implementation is complete and correct before attempting to run it. BMI v2.0 requires all 31 functions to be implemented (even if some return `NotImplementedError` for unused grid types). This stage systematically checks each function.

## Inputs

| Input        | Type   | Description                                     |
|--------------|--------|-------------------------------------------------|
| Module path  | string | Python module path or `.py` file path            |
| Class name   | string | Name of the BMI class within the module          |

## Outputs

| Output            | Format | Description                                  |
|-------------------|--------|----------------------------------------------|
| Compliance report | stdout | Per-function pass/fail with category summary |
| JSON report       | file   | Machine-readable report (optional)           |

## Procedure

1. **Load module**: Import the Python module containing the BMI class
2. **Discover class**: Locate the specified class and verify it's a class
3. **Check each function**: For all 31 BMI functions:
   - Verify method exists on the class
   - Verify method is callable
   - Check method signature matches expected parameter count
4. **Categorize results**: Group by function category (metadata, control, info, variable, time, getter/setter, grid)
5. **Generate report**: Compliance percentage, per-category breakdown, errors, warnings

```bash
# Example usage
python compliance_checker.py heat BmiHeat
python compliance_checker.py /path/to/bmi_heat.py BmiHeat --json report.json
```

## Verification

- [ ] All 31 BMI functions checked
- [ ] Report shows per-category breakdown
- [ ] Missing functions listed as errors
- [ ] Signature mismatches listed as warnings
- [ ] Exit code 0 for compliant, 1 for non-compliant

## BMI v2.0 Function Checklist (31 functions)

### Metadata (1)
- [ ] `get_bmi_version` → str

### Control (4)
- [ ] `initialize(config_file)` → None
- [ ] `update()` → None
- [ ] `update_until(time)` → None
- [ ] `finalize()` → None

### Information (5)
- [ ] `get_component_name` → str
- [ ] `get_input_item_count` → int
- [ ] `get_output_item_count` → int
- [ ] `get_input_var_names` → tuple[str]
- [ ] `get_output_var_names` → tuple[str]

### Variable (6)
- [ ] `get_var_grid(name)` → int
- [ ] `get_var_type(name)` → str
- [ ] `get_var_units(name)` → str
- [ ] `get_var_itemsize(name)` → int
- [ ] `get_var_nbytes(name)` → int
- [ ] `get_var_location(name)` → str

### Time (5)
- [ ] `get_current_time` → float
- [ ] `get_start_time` → float
- [ ] `get_end_time` → float
- [ ] `get_time_units` → str
- [ ] `get_time_step` → float

### Getter/Setter (5)
- [ ] `get_value(name, dest)` → ndarray
- [ ] `get_value_ptr(name)` → ndarray
- [ ] `get_value_at_indices(name, dest, inds)` → ndarray
- [ ] `set_value(name, src)` → None
- [ ] `set_value_at_indices(name, inds, src)` → None

### Grid (15)
- [ ] `get_grid_rank(grid)` → int
- [ ] `get_grid_size(grid)` → int
- [ ] `get_grid_type(grid)` → str
- [ ] `get_grid_shape(grid, shape)` → ndarray
- [ ] `get_grid_spacing(grid, spacing)` → ndarray
- [ ] `get_grid_origin(grid, origin)` → ndarray
- [ ] `get_grid_x(grid, x)` → ndarray
- [ ] `get_grid_y(grid, y)` → ndarray
- [ ] `get_grid_z(grid, z)` → ndarray
- [ ] `get_grid_node_count(grid)` → int
- [ ] `get_grid_edge_count(grid)` → int
- [ ] `get_grid_face_count(grid)` → int
- [ ] `get_grid_edge_nodes(grid, edge_nodes)` → ndarray
- [ ] `get_grid_face_edges(grid, face_edges)` → ndarray
- [ ] `get_grid_face_nodes(grid, face_nodes)` → ndarray
- [ ] `get_grid_nodes_per_face(grid, nodes_per_face)` → ndarray

## Traps

| Trap | Description | Detection | Fix |
|------|-------------|-----------|-----|
| **Abstract base class** | Checking the `Bmi` ABC instead of a concrete implementation | All functions "present" but raise NotImplementedError | Check the concrete subclass, not the base |
| **Missing grid functions** | Developer only implements grid funcs for their grid type | Compliance check shows failures for unused grid types | Implement stubs that raise NotImplementedError |
| **Wrong argument count** | `set_value_at_indices` takes (name, inds, src) not (name, src, inds) | Signature warning in report | Match BMI spec exactly |
| **Instance vs class check** | Checking an instance instead of a class | TypeError | Pass the class, not `class()` |

## Example

```
============================================================
BMI Compliance Report: BmiHeat
============================================================
Status: PASS
Functions: 31/31 (100.0%)

By category:
  metadata             1/ 1 [PASS]
  control              4/ 4 [PASS]
  info                 5/ 5 [PASS]
  variable             6/ 6 [PASS]
  time                 5/ 5 [PASS]
  getter_setter        5/ 5 [PASS]
  grid                15/15 [PASS]
============================================================
```
