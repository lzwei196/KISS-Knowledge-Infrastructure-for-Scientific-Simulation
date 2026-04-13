# Stage 1: Model Initialization

## Purpose

Create the `DeltaModel` object, parsing the configuration, building the computational domain, initializing all field arrays (eta, stage, depth, velocity, discharge), and creating the output NetCDF file.

## Inputs

| Input | Format | Source |
|-------|--------|--------|
| YAML config file | `.yml` | Stage 0 |
| Or keyword arguments | Python dict | Python API |

## Outputs

| Output | Format | Used By |
|--------|--------|---------|
| `DeltaModel` object | Python object | Stages 2-6 |
| Output directory | Filesystem | Contains log, NetCDF |
| Log file | `.log` text | Debugging |
| Initial NetCDF | `.nc` | Time=0 snapshot |

## Procedure

1. **Parse configuration**: `import_files()` reads `default.yml` for defaults, then overlays user YAML values. Type checking is performed against expected types from `default.yml`.

2. **Create output infrastructure**: Creates output directory, initializes logger, sets up save lists for figures and grid variables.

3. **Process inputs to model**: `process_input_to_model()` assigns all config values as model attributes. All parameters are logged.

4. **Set random seed**: If no seed specified, a random seed is generated. The seed is always logged for reproducibility. Uses numba's random generator (not numpy's).

5. **Create derived variables**: `create_other_variables()` computes:
   - Grid dimensions: `L = Length/dx`, `W = Width/dx`
   - Inlet dimensions: `L0 = L0_meters/dx`, `N0 = N0_meters/dx`
   - Flow parameters: `Qw0`, `Qs0`, `gamma`, `dt`, `u_max`, `C0`
   - Deposition/erosion thresholds: `U_dep_mud`, `U_ero_sand`, `U_ero_mud`

6. **Create domain**: `create_domain()` builds:
   - Coordinate arrays (`x`, `y`, `X`, `Y`)
   - Cell type array (land=-2, channel=1, ocean=0, edge=-1)
   - Initial topography (eta), stage, depth
   - Initial velocity and discharge fields

7. **Initialize sediment routers**: Pre-initialize JIT-compiled `SandRouter` and `MudRouter` objects (avoids per-timestep boxing overhead).

8. **Initialize subsidence**: If `toggle_subsidence=True`, creates the sigma subsidence field.

9. **Open output file**: Creates `pyDeltaRCM_output.nc` with appropriate dimensions and variables. Saves initial condition (t=0).

## Verification

- [ ] Log file created in output directory
- [ ] No warnings about unused YAML parameters (check stderr)
- [ ] Grid dimensions match expected: L × W cells
- [ ] `gamma` value logged and < 0.1
- [ ] NetCDF file created (if `save_*_grids = True`)
- [ ] Initial eta shows inlet channel and sloping land

## Traps

| Trap | Symptom | Fix |
|------|---------|-----|
| YAML key typo | Warning: "unused keys" | Check YAML key names against default.yml |
| Wrong type in YAML | TypeError at init | Ensure numbers are numbers, bools are bools |
| Preprocessor keys in DeltaModel | Warning about preprocessor-only keywords | Use `Preprocessor` class for matrix/set/ensemble |
| `resume_checkpoint` without checkpoint file | FileNotFoundError | Set `resume_checkpoint: false` or provide checkpoint |
| Very large grid (L×W > 1e6 cells) | Out of memory | Increase dx or reduce Length/Width |

## Example

```python
import pyDeltaRCM

# Initialize from YAML
delta = pyDeltaRCM.DeltaModel(input_file='config.yml')

# Check key derived parameters
print(f"Grid: {delta.L} x {delta.W} cells")
print(f"dt: {delta._dt:.1f} seconds")
print(f"gamma: {delta.gamma:.5f}")
print(f"Qw0: {delta.Qw0:.1f} m3/s")
print(f"Qs0: {delta.Qs0:.4f} m3/s")

# Check cell type distribution
import numpy as np
for ct, name in [(-2, 'land'), (-1, 'edge'), (0, 'ocean'), (1, 'channel')]:
    print(f"  {name}: {(delta.cell_type == ct).sum()} cells")
```

## Key Internal Variables After Init

| Variable | Shape | Type | Description |
|----------|-------|------|-------------|
| `eta` | (L, W) | float32 | Bed elevation (m) |
| `stage` | (L, W) | float32 | Water surface elevation (m) |
| `depth` | (L, W) | float32 | Water depth (m) |
| `cell_type` | (L, W) | int64 | Cell classification |
| `qx`, `qy` | (L, W) | float32 | Discharge components |
| `ux`, `uy` | (L, W) | float32 | Velocity components |
| `sand_frac` | (L, W) | float32 | Sand fraction (0-1) |
| `inlet` | (N0,) | int64 | Inlet cell y-indices |
