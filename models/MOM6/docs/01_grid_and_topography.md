# Stage 1: Grid Generation and Topography Setup

## Purpose

Create the horizontal grid (supergrid), vertical coordinate definition, and ocean
bottom topography for a MOM6 simulation. This stage defines the model domain
geometry and determines which cells are ocean vs land.

## Inputs

| File / Data          | Format  | Description                                    |
|----------------------|---------|------------------------------------------------|
| Domain bounds        | Config  | Lat/lon extent, resolution                     |
| Global bathymetry    | NetCDF  | GEBCO_2022, ETOPO1, or SRTM30+                |
| Vertical levels      | Config  | Number of layers (NK), coordinate type          |

### Global Bathymetry Sources

- **GEBCO_2022**: 15 arc-second resolution, variable `elevation` in meters (positive up)
- **ETOPO1**: 1 arc-minute resolution, variable `z` in meters (positive up)
- **SRTM30+**: 30 arc-second, variable `z` in meters (positive up)

## Outputs

| File                   | Variable(s)      | Units      | Description              |
|------------------------|------------------|------------|--------------------------|
| `INPUT/ocean_hgrid.nc` | x, y, dx, dy, area, angle_dx | deg, m, m² | Supergrid (2N+1 × 2M+1) |
| `INPUT/topog.nc`       | depth            | m (positive down) | Ocean bottom depth  |
| `INPUT/vcoord.nc`      | interfaces/Layer | m          | Vertical coordinate      |

## Procedure

1. **Generate supergrid**: Use `FRE-NCtools/make_hgrid` or Python `gridtools`:
   ```bash
   make_hgrid --grid_type regular_lonlat_grid \
     --nxbnds 2 --nybnds 2 \
     --xbnds 0,360 --ybnds -80,90 \
     --nlon 720 --nlat 360
   ```

2. **Process topography**:
   ```bash
   python topography_converter.py GEBCO_2022.nc \
     --output INPUT/topog.nc \
     --grid INPUT/ocean_hgrid.nc \
     --min-depth 10 --max-depth 6500 \
     --smooth 2
   ```

3. **Create vertical coordinate**:
   - For z* coordinates: define NK interface depths (e.g., 75 levels, surface-intensified)
   - For isopycnal: define NK target densities
   - Write to `INPUT/vcoord.nc` with variable `interfaces` in meters

4. **Set MOM_input parameters**:
   ```fortran
   NIGLOBAL = 360
   NJGLOBAL = 180
   NK = 75
   TOPO_FILE = "topog.nc"
   TOPO_VARNAME = "depth"
   MINIMUM_DEPTH = 10.0    ! [m]
   MAXIMUM_DEPTH = 6500.0  ! [m]
   ```

## Verification

- [ ] `ocean_hgrid.nc` dimensions are (2*NJ+1, 2*NI+1)
- [ ] `topog.nc` depth values are all >= 0 (positive down convention)
- [ ] No NaN values in depth field
- [ ] Ocean fraction is reasonable (≈70% for global, domain-specific for regional)
- [ ] Minimum depth >= MINIMUM_DEPTH parameter
- [ ] Grid spacing (dx, dy) matches expected resolution

## Traps

| Trap ID | Symptom | Cause | Fix |
|---------|---------|-------|-----|
| dt_005  | All cells masked as land | Elevation not negated to depth | depth = -elevation |
| dt_005  | Crash at initialization  | Negative depth values | Ensure positive-down convention |
| -       | Noisy velocities near coast | Grid-scale topography noise | Increase smoothing passes |
| -       | Domain decomposition error | Grid dims not divisible by PE count | Adjust NIGLOBAL/NJGLOBAL |

## Example

```python
from topography_converter import validate_input, process_topography, validate_output

info = validate_input("GEBCO_2022.nc", grid_path="INPUT/ocean_hgrid.nc")
process_topography(info, "INPUT/topog.nc", min_depth=10.0, max_depth=6500.0, smooth_passes=2)
report = validate_output("INPUT/topog.nc")
print(f"Ocean cells: {report['stats']['n_ocean']}, depth range: "
      f"{report['stats']['min_depth_m']:.0f}-{report['stats']['max_depth_m']:.0f} m")
```
