# Stage 2: Mask Definition (Ice/Ocean Boundaries)

## Purpose

Define which parts of the domain contain grounded ice, floating ice (ice shelves), or open ocean. The mask controls which physics are applied where: floating ice has zero basal friction, grounded ice has bedrock contact, and ocean areas are excluded from the solve.

## Inputs

| Input | Format | Units | Description |
|-------|--------|-------|-------------|
| Model with mesh | `md` object | - | Must have mesh from Stage 1 |
| Floating ice domain | `.exp` file or `'all'`/`''` | - | Contour defining floating regions |
| Grounded ice domain | `.exp` file or `''` | - | Contour defining grounded islands within floating |

## Outputs

| Output | Type | Units | Description |
|--------|------|-------|-------------|
| `md.mask.ocean_levelset` | array[nv] | - | Signed distance: <0 floating, >0 grounded |
| `md.mask.ice_levelset` | array[nv] | - | Signed distance: <0 ice present, >0 no ice |

### Levelset Convention (dt_011)

**CRITICAL**: ISSM uses signed distance functions where **negative = inside**:

| Condition | `ocean_levelset` | `ice_levelset` |
|-----------|-------------------|-----------------|
| Grounded ice | > 0 | < 0 |
| Floating ice (shelf) | < 0 | < 0 |
| Open ocean | < 0 | > 0 |
| Ice-free land | > 0 | > 0 |

Confusing the sign convention inverts the entire ice coverage — the solver will apply basal friction to the ocean and free-slip to grounded ice.

## Procedure

### Simple Cases

```python
from setmask import setmask

# All ice is floating (ice shelf simulation)
md = setmask(md, 'all', '')

# All ice is grounded (ice sheet simulation)
md = setmask(md, '', '')

# Mixed: floating ice defined by contour, some grounded islands
md = setmask(md, 'FloatingDomain.exp', 'GroundedIslands.exp')
```

### From External Data

```python
# Using BedMachine/SeaRISE thickness mask
thk_mask = InterpFromGridToMesh(x1, y1, mask_grid, md.mesh.x, md.mesh.y, 0)
# thk_mask == 1 → grounded, thk_mask == -1 → floating

md.mask.ocean_levelset = thk_mask  # Already in correct convention
md.mask.ice_levelset = -np.ones(md.mesh.numberofvertices)  # All ice
```

### Flotation Criterion

For physics-based mask determination:

```python
# Ice floats when bed < -ρ_ice/ρ_water × thickness
flotation_depth = -917.0 / 1023.0 * md.geometry.thickness
is_floating = md.geometry.bed < flotation_depth

md.mask.ocean_levelset = np.ones(md.mesh.numberofvertices)
md.mask.ocean_levelset[is_floating] = -1.0
```

## Verification

1. **Check sign convention**: `sum(ocean_levelset < 0)` should match expected floating area
2. **Ice coverage**: `sum(ice_levelset < 0)` should cover the entire domain (usually)
3. **Grounding line**: Transition from positive to negative ocean_levelset should follow known GL
4. **Consistency with geometry**: Floating ice should have `bed < -ρ_ice/ρ_water × thickness`

```python
n_floating = np.sum(md.mask.ocean_levelset < 0)
n_grounded = np.sum(md.mask.ocean_levelset > 0)
n_ice = np.sum(md.mask.ice_levelset < 0)
print(f"Grounded: {n_grounded}, Floating: {n_floating}, Ice: {n_ice}")
```

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_011 | Ice velocities inverted (fast where slow expected) | Mask sign convention reversed | Negate `ocean_levelset` |
| dt_005 | Floating ice has unrealistic drag | Non-zero friction where `ocean_levelset < 0` | Set `friction.coefficient = 0` on floating nodes |
| - | Solver fails with "singular matrix" | Missing ice (all `ice_levelset > 0`) | Check mask covers domain |
| - | Grounding line in wrong location | Mask from wrong dataset/resolution | Verify against BedMachine or similar |

## Example

```python
# Greenland with floating outlet glaciers
md = setmask(md, '', '')  # Start all grounded

# Override from SeaRISE mask
import netCDF4
ds = netCDF4.Dataset('Greenland_5km_v1.1.nc')
mask = np.array(ds.variables['thkmask'][:])  # 1=grounded, -1=floating
x1 = np.array(ds.variables['x1'][:])
y1 = np.array(ds.variables['y1'][:])

ocean_ls = InterpFromGridToMesh(x1, y1, mask.T, md.mesh.x, md.mesh.y, 0)
md.mask.ocean_levelset = ocean_ls  # Positive=grounded, negative=floating
md.mask.ice_levelset = -np.ones(md.mesh.numberofvertices)  # All ice

# Verify
n_float = np.sum(md.mask.ocean_levelset < 0)
print(f"Floating vertices: {n_float} / {md.mesh.numberofvertices}")
```
