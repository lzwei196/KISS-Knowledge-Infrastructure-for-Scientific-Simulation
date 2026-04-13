# Skill Document: Numerical Node Discretization (S5)

**Stage:** s5_node_discretization
**Pipeline Order:** 5
**Depends On:** s4_soil_setup (requires horizon depths to be set in RZWQM.dat)
**Tool:** `generate_nodes`

---

## Purpose

Generate the computational node grid for RZWQM2's finite-difference numerical solver. The model simulates soil water flow using the Richards equation, which requires the soil profile to be divided into discrete computational nodes (layers). The `nlayer_gen` algorithm creates these nodes following a "half-way rule" that ensures node boundaries align with soil horizon boundaries. This alignment is critical for numerical stability and for correctly associating soil properties (which are defined per horizon) with computational nodes.

The algorithm starts with thin layers near the surface (1 cm) and progressively increases layer thickness deeper in the profile, which provides high resolution where gradients are steepest (near the surface) while keeping the total node count manageable.

---

## Prerequisites

1. Soil horizon depths have been defined and written to `RZWQM.dat` (S4 complete).
2. Horizon depths are in ascending order, all positive, and the deepest horizon does not exceed 3000 cm.
3. Number of horizons does not exceed 20 (MAXHOR).
4. Python environment with access to `rzwqm_file.py` (specifically the `RZWQM` class and `nlayer_gen` / `ncoslyr` functions).

---

## Inputs

| Parameter | Type | Unit | Description | Example |
|-----------|------|------|-------------|---------|
| `project_path` | string (directory) | -- | RZWQM2 project root | `/Users/leo/Desktop/RZWQM2/projects/` |
| `station_id` | string | -- | Scenario identifier | `534` |
| `horizon_depths` | list of floats | cm | Bottom depth of each soil horizon | `[15.0, 30.0, 60.0, 100.0, 200.0]` |

---

## Procedure

### Step 1: Understand the nlayer_gen Algorithm

The node generation algorithm (`nlayer_gen` in `rzwqm_file.py`) works as follows:

1. **Initialize layer thickness array (`delz`)** using `makedelz(last_horizon_depth)`:
   - Starts with `delz[0] = delz[1] = 1.0` cm (first two nodes are 1 cm thick).
   - Thickness increases by 2 cm every 2 nodes: `delz[2] = delz[3] = 3.0`, `delz[4] = delz[5] = 5.0`, etc.
   - Maximum thickness (`maxval`) depends on profile depth:
     - Profile <= 1400 cm: maxval = 5 cm
     - 1400 < profile <= 2000 cm: maxval = 7 cm
     - 2000 < profile <= 2500 cm: maxval = 9 cm
     - 2500 < profile <= 3000 cm: maxval = 11 cm
   - Once maxval is reached, all remaining layers have thickness = maxval+2 (the jump value continues but never exceeds the next odd value).

2. **Compute node positions** using `maketl` and `maketlt`:
   - `tl[i]` = half-distance between node centers (used as numerical weight).
   - `tlt[i]` = cumulative depth of the bottom of each node.

3. **Apply the half-way rule** (`ncoslyr`):
   - For each horizon boundary (except the last), find the node whose bottom depth (`tlt[pos]`) is closest to or equal to the horizon depth.
   - If the node boundary does not exactly match the horizon depth, decrement node thicknesses (`decrement_delz`) by 2 cm increments until alignment is achieved.
   - After alignment, mirror the node thickness on the other side of the boundary (`mirror`) and propagate forward (`forwardhalf`).

4. **Adjust horizon depths if needed**:
   - If exact alignment is impossible, the algorithm slightly adjusts the horizon depth to match the nearest node boundary.
   - A message is printed: `"To accommodate our numerical layering scheme, one of your horizon depths had to be changed."`

5. **Error recovery**:
   - If `ncoslyr` fails (returns `False`), the algorithm tries adjusting each horizon depth by +/- 1 to 10 cm and re-running until a valid grid is found.

### Step 2: Generate Nodes

```python
from rzwqm_file import RZWQM

rz = RZWQM(project_path, station_id)

horizon_depths = [15.0, 30.0, 60.0, 100.0, 200.0]
node_data = rz.generate_node_data(horizon_depths)
# Returns: list of [node_index, cumulative_depth, layer_thickness]
# Example: [[0, 1.0, 1.0], [1, 2.0, 1.0], [2, 5.0, 3.0], ...]
```

The returned list contains tuples of `[node_index, depth_cm, thickness_cm]` for all nodes up to and including the deepest horizon.

### Step 3: Write Nodes to RZWQM.dat

```python
rz.write_soil_node_to_dat(node_data)
```

This writes to the node discretization section of RZWQM.dat (between identifiers `'=       record (depth increasing with node no.)'` and `'=         SOIL HORIZON PHYSICAL PROPERTIES'`). The format is:

```
{total_node_count}
{node_num}  {depth_cm}  {thickness_cm}
{node_num}  {depth_cm}  {thickness_cm}
...
```

Node numbers are 1-based in the file (the code adds 1 to the 0-based index).

### Step 4: Update Horizon Depths If Adjusted

If the algorithm adjusted any horizon depths to fit the discretization grid, update the horizon depths in RZWQM.dat:

```python
# The nlayer_gen function modifies horizon_depths in-place
# After calling generate_node_data, check if depths changed:
rz.write_soil_horizon_depth_to_dat(horizon_depths)
```

Alternatively, use the combined method that does both:

```python
rz.insert_new_horizon_to_existing_dat_file(horizon_depths)
```

This calls `generate_node_data` and `write_soil_node_to_dat` internally, and also updates horizon depths if they were adjusted.

### Step 5: Verify Node-Horizon Alignment

After writing, verify that node boundaries align with horizon boundaries:

```python
nodes = rz.return_soil_nodes()
# Returns: {horizon_num: [list of node indices in that horizon]}
# Verify that the last node in each horizon has a depth matching the horizon depth
```

---

## Expected Outputs

- **Modified file:** `{project_path}/{station_id}/RZWQM.dat`
- **Modified section:** Node discretization section, containing:
  - Line 1: Total number of nodes
  - Lines 2+: One line per node with `node_number  depth  thickness`
- **Typical node counts:** 30-100 nodes for profiles 100-300 cm deep.
- **Horizon depths may be slightly adjusted** (typically by 1-5 cm) to accommodate the discretization scheme.

---

## Validation Checks

1. **Node count <= 300 (MAXNOD):** The algorithm must not produce more than 300 nodes. If it does, the profile is too deep or horizons are spaced in a way that prevents efficient discretization.
2. **Horizon count <= 20 (MAXHOR):** No more than 20 horizons are allowed.
3. **Maximum depth <= 3000 cm:** Profile depth must not exceed 3000 cm.
4. **Node depth monotonically increasing:** Each node depth must be greater than the previous.
5. **Horizon alignment:** For each horizon boundary, there must be a node whose bottom depth matches (or very closely approximates) the horizon depth.
6. **Layer thickness progression:** Thicknesses should generally increase with depth, starting at 1 cm near the surface.
7. **No zero or negative thicknesses:** All `delz` values must be positive.

---

## Common Pitfalls

### PITFALL 1: Horizons Too Close Together (FATAL)
**Severity:** Fatal -- the algorithm fails and returns `False`.
**Symptom:** `nlayer_gen` returns `False` or the error recovery loop exhausts all adjustment attempts.
**Cause:** Two horizon boundaries are so close together (e.g., 1-2 cm apart) that the discretization algorithm cannot place a node boundary at both locations while satisfying the half-way rule.
**Fix:** Merge very thin horizons (less than 5 cm thick) with adjacent horizons. The minimum practical horizon thickness is approximately 3-5 cm. If the algorithm adjusts depths, accept the adjustments unless they fundamentally change the soil profile representation.

### PITFALL 2: Horizon Depths Modified Without User Awareness (SILENT ADJUSTMENT)
**Severity:** Minor -- but can cause confusion.
**Symptom:** After node generation, the horizon depths in RZWQM.dat differ from the originally specified depths by 1-5 cm.
**Cause:** The half-way rule requires node boundaries to fall exactly on horizon boundaries. When this is not possible with the default thickness progression, the algorithm adjusts horizon depths.
**Detection:** The algorithm prints a message when it adjusts depths. Compare the horizon depths before and after node generation.
**Fix:** Accept the adjusted depths and ensure they are written back to RZWQM.dat and are consistent with RZINIT.dat.

### PITFALL 3: Node Count Explosion for Very Deep Profiles
**Severity:** Potential fatal if > 300 nodes.
**Cause:** Very deep profiles (> 2000 cm) with many thin horizons near the surface can produce excessive nodes.
**Fix:** For deep profiles, use fewer horizons near the surface or increase the minimum horizon thickness. The algorithm's `maxval` increases for deeper profiles (up to 11 cm), but the initial fine-resolution zone near the surface always uses 1 cm layers.

### PITFALL 4: Not Re-writing Horizon Depths After Adjustment
**Severity:** Moderate -- RZWQM.dat will have inconsistent information.
**Cause:** The `nlayer_gen` function modifies the `horizon_depths` list in place, but if `write_soil_horizon_depth_to_dat` is not called afterwards, the horizon depth section of RZWQM.dat will have the original (non-adjusted) depths while the node section uses the adjusted depths.
**Fix:** Always use `insert_new_horizon_to_existing_dat_file(horizon_depths)` which handles both node generation and horizon depth updates atomically. Or, explicitly call `write_soil_horizon_depth_to_dat` after node generation.
