# Stage 3: Parameterization (Data Loading and Model Setup)

## Purpose

Load all physical parameters onto the mesh: ice geometry (surface, base, thickness), material properties (rheology, density), friction coefficients, boundary conditions, and initial conditions. This is the most data-intensive stage and the most common source of silent unit errors.

## Inputs

| Input | Format | Units | Description |
|-------|--------|-------|-------------|
| Model with mesh + mask | `md` object | - | From Stages 1-2 |
| Parameter file | `.par` (MATLAB) or `.py` (Python) | - | Script that populates md fields |
| External datasets | NetCDF, archive, npy | Various | Geometry, velocity, temperature, SMB |

## Outputs

All fields populated on the `md` object:

| Field | Units | Source | Description |
|-------|-------|--------|-------------|
| `md.geometry.surface` | m | BedMachine/SeaRISE | Ice surface elevation |
| `md.geometry.base` | m | Computed | Ice base elevation |
| `md.geometry.thickness` | m | BedMachine/SeaRISE | Ice thickness |
| `md.geometry.bed` | m | BedMachine | Bedrock topography |
| `md.materials.rheology_B` | Pa s^(1/n) | `paterson(T)` | Ice viscosity parameter |
| `md.materials.rheology_n` | - | Constant (3) | Glen's flow law exponent |
| `md.friction.coefficient` | (Pa m^-1 s)^(1/2) | Inversion/estimate | Basal friction |
| `md.friction.p` | - | Constant (1) | Friction law exponent |
| `md.friction.q` | - | Constant (1) | Friction law exponent |
| `md.initialization.vx` | m/yr | MEaSUREs/InSAR | Initial x-velocity |
| `md.initialization.vy` | m/yr | MEaSUREs/InSAR | Initial y-velocity |
| `md.initialization.temperature` | K | Climate model | Initial temperature |
| `md.smb.mass_balance` | m/yr ice equiv. | RACMO2/MAR | Surface mass balance |
| `md.basalforcings.geothermalflux` | W/m^2 | Shapiro/Fox-Maule | Geothermal heat flux |

## Procedure

### Standard Parameterization

```python
md = parameterize(md, 'Greenland.py')
```

The `.py` file is executed with `md` in scope and typically does:

```python
# 1. Load external data
import netCDF4
ds = netCDF4.Dataset('Greenland_5km_v1.1.nc')
x1 = np.array(ds.variables['x1'][:])
y1 = np.array(ds.variables['y1'][:])

# 2. Interpolate geometry onto mesh
usrf = np.array(ds.variables['usrf'][:])
topg = np.array(ds.variables['topg'][:])
md.geometry.surface = InterpFromGridToMesh(x1, y1, usrf.T, md.mesh.x, md.mesh.y, 0)
md.geometry.bed = InterpFromGridToMesh(x1, y1, topg.T, md.mesh.x, md.mesh.y, 0)
md.geometry.thickness = md.geometry.surface - md.geometry.bed
md.geometry.base = md.geometry.bed  # Grounded ice

# 3. Set material properties
temp = InterpFromGridToMesh(x1, y1, T.T, md.mesh.x, md.mesh.y, 0) + 273.15  # °C → K!
md.materials.rheology_B = paterson(temp)
md.materials.rheology_n = 3 * np.ones(md.mesh.numberofelements)

# 4. Set friction (0 on floating ice)
md.friction.coefficient = 30 * np.ones(md.mesh.numberofvertices)
md.friction.coefficient[md.mask.ocean_levelset < 0] = 0  # CRITICAL (dt_005)
md.friction.p = np.ones(md.mesh.numberofelements)
md.friction.q = np.ones(md.mesh.numberofelements)

# 5. Set boundary conditions
md = SetIceShelfBC(md, 'Front.exp')  # or SetMarineIceSheetBC(md)

# 6. Set initial conditions
md.initialization.vx = InterpFromGridToMesh(x1, y1, vx.T, md.mesh.x, md.mesh.y, 0)
md.initialization.vy = InterpFromGridToMesh(x1, y1, vy.T, md.mesh.x, md.mesh.y, 0)
md.initialization.temperature = temp  # Must be in Kelvin (dt_002)
```

### Key Interpolation Function

```python
# InterpFromGridToMesh(grid_x, grid_y, grid_data, mesh_x, mesh_y, default)
#   grid_x: 1D array of grid x-coordinates (m, ascending)
#   grid_y: 1D array of grid y-coordinates (m, ascending)
#   grid_data: 2D array [ny, nx] — NOTE: may need .T (transpose) depending on source
#   mesh_x, mesh_y: vertex coordinates
#   default: value for points outside grid (0 is common)
```

## Verification

1. **Geometry consistency**: `surface = base + thickness` everywhere (dt_018)
2. **Temperature in Kelvin**: `min(temperature) > 200` (should be ~220-273 K for ice)
3. **Velocity in m/yr**: `max(vel) < 20000` (realistic for ice sheets)
4. **Friction on floating ice**: `friction.coefficient == 0` where `ocean_levelset < 0`
5. **Positive thickness**: `min(thickness) > 0` everywhere with ice
6. **Rheology B**: `min(B) > 1e6` (Pa s^1/3), `max(B) < 1e9`

```python
# Verification checks
assert np.all(md.geometry.thickness > 0), "Negative thickness (dt_003)"
assert np.all(md.initialization.temperature > 200), "Temperature likely in °C (dt_002)"
assert np.all(md.friction.coefficient[md.mask.ocean_levelset < 0] == 0), "Friction on floating ice (dt_005)"
residual = np.abs(md.geometry.surface - (md.geometry.base + md.geometry.thickness))
assert np.max(residual) < 0.01, f"Geometry inconsistency: {np.max(residual):.4f} m (dt_018)"
```

## Traps

| Trap | Symptom | Cause | Fix |
|------|---------|-------|-----|
| dt_002 | Unrealistic rheology, ice too stiff or soft | Temperature in °C, not K | Add 273.15 before `paterson()` |
| dt_003 | Geometry looks flat or zero | Thickness in km, not m | Multiply by 1000 |
| dt_005 | Ice shelf moves too slowly | Non-zero friction on floating ice | Set friction=0 where `ocean_levelset < 0` |
| dt_006 | Velocity orders of magnitude wrong | Using A instead of B for rheology | Use `B = A^(-1/n)` or `paterson()` |
| dt_012 | Artificial ice divides or frozen boundaries | Using 0 instead of NaN for free BCs | Use NaN for unconstrained nodes |
| dt_018 | Solver instability | `surface ≠ base + thickness` | Recompute one from other two |

## Example

```python
# SquareIceShelf parameterization (simplest case)
hmin = 300   # m — minimum thickness at outflow
hmax = 1000  # m — maximum thickness at inflow
ymin = min(md.mesh.y)
ymax = max(md.mesh.y)

# Linear thickness gradient
md.geometry.thickness = hmax + (hmin - hmax) * (md.mesh.y - ymin) / (ymax - ymin)
md.geometry.base = -md.materials.rho_ice / md.materials.rho_water * md.geometry.thickness
md.geometry.surface = md.geometry.base + md.geometry.thickness

# Uniform rheology (isothermal at -10°C = 263.15 K)
md.materials.rheology_B = paterson(263.15) * np.ones(md.mesh.numberofvertices)
md.materials.rheology_n = 3 * np.ones(md.mesh.numberofelements)

# No friction (all floating)
md.friction.coefficient = np.zeros(md.mesh.numberofvertices)
md.friction.p = np.ones(md.mesh.numberofelements)
md.friction.q = np.ones(md.mesh.numberofelements)

# Ice shelf boundary conditions
md = SetIceShelfBC(md, 'Front.exp')
```
