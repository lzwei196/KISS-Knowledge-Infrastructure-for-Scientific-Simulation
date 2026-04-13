# Stage 2: Grid and River Network Preparation

## Purpose

Prepare or validate the mosartwmpy domain grid file, which defines the river network topology, channel geometry, and hillslope properties for every grid cell. This is the foundational spatial dataset that remains constant throughout a simulation.

## Inputs

| Input | Format | Source | Description |
|-------|--------|--------|-------------|
| Grid domain file | NetCDF | NLDAS, MERIT-Hydro, custom | River network topology + geometry |
| DEM data (optional) | GeoTIFF/NetCDF | MERIT DEM | For slope computation |
| River width data (optional) | NetCDF | GRWL/Allen et al. | Satellite-derived widths |

## Outputs

| Output | Format | Description |
|--------|--------|-------------|
| `mosart_grid.nc` | NetCDF | Complete domain file with all required variables |

### Required Variables in Grid File

| Variable | Name | Units | Physical Meaning |
|----------|------|-------|-----------------|
| ID | `ID` | integer | Unique cell identifier |
| Downstream ID | `dnID` | integer | ID of downstream cell (-1 = outlet) |
| Flow direction | `fdir` | D8 code | 8-direction flow routing |
| Area | `area` | m² | Local drainage area |
| Upstream area | `areaTotal2` | m² | Total single-flow upstream area |
| Land fraction | `frac` | 0-1 | Land fraction of cell |
| Channel length | `rlen` | m | Main channel reach length |
| Channel width | `rwid` | m | Bankfull channel width |
| Channel depth | `rdep` | m | Bankfull channel depth |
| Channel slope | `rslp` | m/m | Main channel bed slope |
| Channel Manning's n | `nr` | s/m^(1/3) | Main channel roughness |
| Hillslope slope | `hslp` | m/m | Overland surface slope |
| Hillslope Manning's n | `nh` | s/m^(1/3) | Overland roughness |
| Drainage density | `gxr` | m⁻¹ | Total channel length per area |

## Procedure

1. **Obtain or create grid file** matching simulation domain
2. **Verify all required variables** are present
3. **Check units**:
   - Area must be m² (not km²)
   - Slopes must be m/m (not percent or degrees)
   - Widths and lengths must be m (not km)
4. **Verify river network connectivity**:
   - Each `dnID` must reference a valid `ID` or be -1
   - No circular references
   - Outlets should have `fdir < 0` or `fdir == 0`
5. **Fill missing values**:
   - Zero slopes → minimum (0.005 hillslope, 0.0001 channel/subnetwork)
   - Zero areas → recomputed from lat/lon spacing
   - Missing Manning's n → defaults (0.075, 0.035, 0.030)
6. **Validate output** with the KI grid validation tool

## Verification

- [ ] All 19 required variables present
- [ ] No circular river network references
- [ ] Slopes are positive and in m/m (typical range: 0.0001-0.5)
- [ ] Areas are in m² (typical 1/8° cell: ~1.2e8 m²)
- [ ] Manning's n in valid range (0.01-0.15)
- [ ] Channel widths positive where `rlen > 0`
- [ ] Grid is uniform rectilinear (equal spacing in lat and lon)

## Traps

### TRAP 1: Area in km² instead of m²
**Symptom**: Discharge is ~1e-6 of expected values.
**Diagnosis**: Grid area not converted from km² to m².
**Prevention**: Check `max(area)` — should be ~1e8 for 1/8° grid, not ~100.

### TRAP 2: Slope in percent instead of m/m
**Symptom**: Extremely high velocities, numerical instability.
**Diagnosis**: Slope=10 means 10% but Manning's equation expects 0.10.
**Prevention**: If max slope > 1.0, likely in percent — divide by 100.

### TRAP 3: Missing floodplain width
**Symptom**: Water disappears during flood events.
**Diagnosis**: `rwid0` (floodplain width) is zero or absent.
**Prevention**: Set `rwid0 = max(rwid * 5, sqrt(area))` as default.

### TRAP 4: Disconnected river network
**Symptom**: Water accumulates in interior cells, never reaches outlets.
**Diagnosis**: Some `dnID` values point to non-existent cells.
**Prevention**: Run connectivity check: all paths from any cell must reach an outlet.

## Example

```python
from ki.tools.convert_grid_parameters import convert_grid, validate_grid
import xarray as xr

# Validate existing grid file
ds = xr.open_dataset('./input/domains/mosart_conus_nldas_grid.nc')
issues = validate_grid(ds)
for issue in issues:
    print(issue)

# Convert and fill defaults
result = convert_grid(
    input_path='./raw_grid.nc',
    output_path='./input/domains/mosart_grid.nc',
    fill_defaults=True,
)
```
